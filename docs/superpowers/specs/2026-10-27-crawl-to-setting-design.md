# SQLite 기반 기본상품/판매상품 관리 → xlsx 출력 설계

## 의도와 목적
크롤 결과를 SQLite DB에 저장하고, 사용자가 DB에서 정보를 추가·수정한 뒤, DB를 기준으로 Playauto용 `setting`과 최종 `_단일/_일반/_쿠팡.xlsx`를 출력한다.

앞으로 가격 변동 알람, 상품고시/상세페이지 생성, 묶음 수량별 이미지 생성 기능이 추가된다. 이번 단계에서는 그 기반이 되는 **기본상품(products)** 과 **판매상품(listings)** 분리, 주문 링크, 가격 이력 저장, import/export를 구현한다.

## 이번 단계 범위
- SQLite 파일 DB와 스키마
- 기본상품/판매상품 분리
- 크롤 5열 import/upsert
- 가격 이력 저장
- DB → setting xlsx → 최종 xlsx export
- 기존 직접 xlsx 변환 경로 유지

## 이번 단계 비목표
- 가격 차이 알람 발송
- 상품고시/상세페이지 생성
- 묶음 수량별 이미지 수정 생성
- 자체 DB 편집 GUI/웹
- 크롤러 자체 구현
- 기존 `261009.xlsx` setting 데이터의 DB 이관
- MySQL/PostgreSQL 같은 서버 DB
- `template` 시트 수정
- 상품별 템플릿 코드(`2박스`, `3박스`) 지원

## 확정된 요구사항
- DB 편집은 DB Browser for SQLite 같은 외부 GUI로 직접 한다.
- `template` 시트는 수정하지 않는다.
- 템플릿 코드는 `1박스`로 고정한다.
- 기존 setting/template 워크북을 참조 템플릿으로 재사용한다.
- 주문용 `URL`을 저장한다.
- 최종 Playauto 파일에는 주문용 `URL`을 넣지 않는다.
- 상품은 기본 1개 단위로 관리하고, 판매상품은 2개 이상 묶음이 될 수 있다.
- 상품고시는 기본상품에 연결해 묶음 판매상품이 공유한다. 이번 단계에서는 테이블만 고려하고 UI/생성은 이후 단계다.

## 데이터 모델
### products
기본 1개 단위 상품.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 내부 ID |
| `source_seq` | INTEGER NOT NULL | 크롤 순번 |
| `name` | TEXT NOT NULL | 기본 상품명 |
| `image_url` | TEXT NOT NULL | 원본 대표이미지 |
| `order_url` | TEXT NOT NULL UNIQUE | 주문용 상품 링크 |
| `category_code` | TEXT NOT NULL | 카테고리코드 |
| `detail` | TEXT | 상세설명 |
| `keywords` | TEXT | 키워드 |
| `manufacturer` | TEXT | 제조사 |
| `brand` | TEXT | 브랜드 |
| `model` | TEXT | 모델명 |
| `created_at` | TEXT NOT NULL | ISO 시각 |
| `updated_at` | TEXT NOT NULL | ISO 시각 |
| `last_seen_at` | TEXT NOT NULL | 마지막 크롤 시각 |
| `last_batch_id` | INTEGER | 마지막 import 배치 |

### listings
실제 판매 단위. 기본상품 하나에 1개, 2개, 3개 묶음 판매상품이 붙을 수 있다.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 내부 ID |
| `product_id` | INTEGER NOT NULL | `products.id` |
| `seller_code` | TEXT NOT NULL UNIQUE | 판매자관리코드 |
| `bundle_qty` | INTEGER NOT NULL DEFAULT 1 | 묶음 수량 |
| `sale_name` | TEXT NOT NULL | 판매 상품명 |
| `market_price` | INTEGER NOT NULL | 판매 기준가 |
| `margin_rate` | REAL NOT NULL DEFAULT 0.15 | 마진율 |
| `unit_price_visible` | TEXT | 단위 가격 표시 여부 |
| `display_capacity` | TEXT | 표시 용량 |
| `display_unit` | TEXT | 표시 단위 |
| `pack_config` | TEXT | 구성 방식 |
| `capacity_per_unit` | TEXT | 개당 용량 |
| `active` | INTEGER NOT NULL DEFAULT 1 | 1이면 export 대상 |
| `created_at` | TEXT NOT NULL | ISO 시각 |
| `updated_at` | TEXT NOT NULL | ISO 시각 |

제약/인덱스:
- `UNIQUE(product_id, bundle_qty)` — 한 상품의 같은 묶음 수량은 하나의 판매상품.
- `INDEX(active)`, `INDEX(product_id)`.

### price_history
크롤할 때마다 판매상품 가격을 기록한다. 이번 단계에서는 저장만 하고 알람은 이후 단계다.

`id`, `product_id`, `listing_id`, `price`, `observed_at`, `batch_id`, `crawl_path`.

### import_batches
`id`, `imported_at`, `crawl_path`, `row_count`, `inserted_count`, `updated_count`, `skipped_count`.

### 이후 단계용 확장 지점
- `disclosures`: `product_id`에 연결. 묶음 판매상품은 기본상품의 고시를 공유.
- `product_images`: 원본/묶음 수량별 생성 이미지.
- `detail_pages`: 상품별 상세페이지 HTML/리소스.
- `price_alerts`: `price_history`와 비교 규칙.

이번 단계에서는 위 테이블을 만들지 않는다.

## DB
- 기본 경로: `data/playauto.db`
- CLI `--db PATH`로 변경 가능
- 없으면 부모 디렉터리와 DB를 자동 생성한다.
- `PRAGMA user_version=1`로 스키마 버전을 기록한다.

## 크롤 입력
첫 시트의 첫 행을 헤더로 사용한다.

필수 헤더(공백 제거 후 정확히 일치):
- `순번`
- `대표이미지`
- `상품명`
- `판매가격`
- `URL`

선택 헤더:
- `판매자관리코드`, `마진율`, `상세설명`, `키워드`, `제조사`, `브랜드`, `모델명`
- `단위 가격 표시 여부`, `표시 용량`, `표시 단위`, `구성 방식`, `개당 용량`

규칙:
- 완전히 빈 행은 건너뛴다.
- 값이 일부라도 있는 행에서 필수 값이 비면 행 번호와 헤더를 포함해 실패한다.
- `판매가격`은 숫자, 콤마 포함 문자열, `원` 접미사를 허용한다.
- `순번`은 정수로 변환한다.

## import 동작
### 기본상품 upsert
`order_url`로 찾는다.

신규:
- `products` insert.
- `source_seq`, `name`, `image_url`, `order_url`, `category_code`(CLI 값), 선택 메타데이터, `detail` 저장.

기존:
- `source_seq`, `name`, `image_url`, `last_seen_at`, `last_batch_id` 갱신.
- `category_code`, `detail`, `keywords`, `manufacturer`, `brand`, `model`은 사용자 편집값이므로 보존.

### 판매상품 upsert
항상 `bundle_qty=1` 판매상품을 찾는다.

신규:
- `seller_code`: 크롤 선택 값이 있으면 사용, 없으면 `MJ-{순번:04d}`. 충돌 시 `-2`, `-3`.
- `sale_name` = 크롤 `상품명`
- `market_price` = 크롤 `판매가격`
- `margin_rate` = 크롤 선택 값 또는 CLI `--margin`
- 단위가격 선택 열 저장
- `active=1`

기존:
- `market_price`만 갱신한다.
- `seller_code`, `sale_name`, `margin_rate`, 단위가격, `active`는 보존한다.

### 가격 이력
import한 각 판매상품에 대해 `price_history`를 1행 추가한다. 가격이 같아도 기록한다.

### 기타
- 같은 크롤 안에 같은 URL이 두 번 나오면 마지막 행의 크롤 필드가 남는다.
- 사용자가 DB에서 만든 `bundle_qty=2/3` 판매상품은 import가 건드리지 않는다.
- 신규 상품의 `bundle_qty=1` 판매상품이 없으면 다시 만든다.

## export 동작
1. `listings JOIN products`에서 `listings.active=1`을 `products.source_seq, listings.bundle_qty, listings.id` 순으로 읽는다.
2. 필수 값(`seller_code`, `sale_name`, `market_price`, `margin_rate`, `image_url`, `order_url`, `category_code`)을 검증한다. 누락 시 listing id와 컬럼을 포함해 실패한다.
3. 참조 워크북을 `{date}_플레이오토_설정.xlsx`로 복사한다.
4. 복사본의 `setting` 시트만 새 헤더/행으로 교체한다.
5. `template`과 `Sheet1` 등 다른 시트는 값/스타일을 수정하지 않는다.
6. setting의 마지막 빈 헤더 칸을 `주문링크`로 사용해 `products.order_url`을 기록한다. setting은 18열을 유지한다.
7. setting을 저장한다.
8. 생성된 setting을 기존 Phase1에 넣어 최종 파일을 만든다. setting 복사는 다시 하지 않는다.
9. 최종 `_단일/_일반/_쿠팡` 파일에는 `주문링크`가 포함되지 않는다.

참고: openpyxl로 참조 워크북을 열고 저장하므로 파일이 다시 쓰인다. `template` 셀 값과 스타일은 바꾸지 않지만 바이트 단위 동일성은 보장하지 않는다.

## setting 매핑
| setting 헤더 | 값 |
|---|---|
| `카테고리코드` | `products.category_code` |
| `템플릿코드정보` | 항상 `1박스` |
| `판매자관리코드` | `listings.seller_code` |
| `온라인 상품명` | `listings.sale_name` |
| `시장가격` | `listings.market_price` |
| `마진율` | `listings.margin_rate` |
| `기본이미지` | `products.image_url` |
| `상세설명` | `products.detail` |
| `키워드` | `products.keywords` |
| `제조사` | `products.manufacturer` |
| `브랜드` | `products.brand` |
| `모델명` | `products.model` |
| 단위가격 5개 | `listings` 대응 컬럼 |
| 마지막 빈 헤더 | `products.order_url` (`주문링크`) |

## CLI
`run_converter.py`가 첫 인자로 하위 명령을 받는다. 하위 명령이 없으면 기존 직접 변환 CLI로 동작한다.

### DB import
```
python run_converter.py db-import --db data/playauto.db --crawl crawl.xlsx --category-code "기타재화[35]" --margin 0.15
```
출력 JSON: `db`, `batch_id`, `inserted`, `updated`, `skipped`.

### DB export
```
python run_converter.py db-export --db data/playauto.db --reference 261009.xlsx --output-dir out --date 2026-10-27 --option "기타재화[35]"
```
- `--coupang-single`, 수수료 옵션, `--option`은 기존 Phase1 옵션을 그대로 사용한다.
- `--no-setting-copy`는 지원하지 않는다. DB export는 항상 setting을 만든다.
- 출력 JSON: `setting`, `single`, `general`(또는 `coupang`).

### 기존 직접 변환
기존 `python run_converter.py <setting_template.xlsx> --output-dir ...`는 변경 없이 유지한다.

## 파일/함수 설계
- `playauto/db.py`
  - `connect(db_path)`, `ensure_schema(conn)`
  - `CrawlRow`, `CrawlData`, `load_crawl_rows(path) -> CrawlData`
  - `import_crawl(conn, crawl: CrawlData, category_code, margin, crawl_path) -> ImportSummary`
  - `fetch_export_rows(conn) -> list[ExportRow]`
  - `validate_export_rows(rows)`
- `playauto/db_export.py`
  - `write_setting_from_rows(reference_path, rows, output_path) -> Path`
  - `export_from_db(...) -> dict`
- `playauto/db_cli.py`
  - `db-import`, `db-export` argparse
- `playauto/xlsx.py`
  - 기존 `convert_phase1(..., copy_setting=False)` 재사용
- `run_converter.py`
  - 하위 명령 dispatch 추가
- `tests/test_db.py`
  - schema, product/listing insert, upsert 보존, seller code 충돌, 가격 이력, 가격/순번 파싱, 필수 헤더/값 오류
- `tests/test_db_export.py`
  - listing 기준 export, 18열 유지, `주문링크` 기록, template 셀 불변, 최종 파일에 URL 없음, 가격 계산, 2/3 묶음 판매상품 export
- `tests/test_db_cli.py`
  - import → DB 수정 → export end-to-end

## 오류 처리
- 필수 헤더 누락: `[크롤] 누락 헤더: ...`
- 필수 값 누락: `[크롤] N행 '상품명' 값이 비어 있습니다.`
- 잘못된 가격/순번: 행 번호 포함
- export 필수 값 누락: `[DB] listing id=... 'order_url' 값이 비어 있습니다.`
- 참조 워크북 시트 누락: 기존과 동일하게 `필수 시트 누락: ...`
- DB 파일이 손상됐거나 열 수 없으면 sqlite3 오류를 그대로 전달한다.

## 검증
- 전체 unittest 통과.
- 테스트용 크롤 2~3행으로 import → DB에서 마진율/카테고리/메타데이터 수정 → 재import → 수정값 보존 확인.
- DB에서 `bundle_qty=2` 판매상품을 추가하고 export 시 별도 setting 행이 나오는지 확인.
- export 후 setting 18열, `주문링크` 존재, template 셀 값 동일, 최종 파일에 `주문링크` 없음 확인.
- 단일/일반 판매가가 각 수수료로 계산되는지 확인.
- 실제 `261009.xlsx` 참조로 end-to-end 실행.

## 가정/남은 결정
- DB 편집 도구는 DB Browser for SQLite를 기본으로 가정한다.
- `MJ-{순번:04d}`는 구현 기본값이며 DB에서 수정 가능하다.
- 카테고리코드는 기본상품 컬럼으로 두고, import 시 CLI 단일 값을 기본 입력한다.
- `active=0`으로 바꾸면 export에서 제외된다.
- 묶음 수량별 가격은 사용자가 DB에서 판매상품별로 입력한다. 자동 배수 계산은 이번 단계 비목표다.
- 가격 알람, 상품고시/상세페이지, 묶음 이미지 생성은 다음 단계다.
