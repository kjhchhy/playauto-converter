# Gmarket 검색 수집 · 웹 관리 · Playauto 출력 설계

## 의도와 목적

LXC에서 상시 운영하는 단일 관리자 웹 앱을 만든다. 관리자는 Gmarket 스타배송 검색 URL을 붙여넣고, 검색 결과 전체를 한 번에 DB에 등록한다. 이후 웹에서 상품을 조회·수정·삭제하고, DB를 기준으로 Playauto용 설정/최종 xlsx를 생성·다운로드한다.

이번 단계의 핵심은 **검색 결과 수집 → DB 등록 → 정리 → xlsx 출력**을 웹에서 끝내는 것이다. 주기적 재크롤링, 경쟁 상품 가격 추적, 상세페이지 생성은 범위 밖이다.

## 확정된 요구사항

- 실행 환경: Proxmox LXC, 원격 접속 가능한 웹 앱
- 관리자: 단일 관리자
- 상품 수: 활성 상품 2,000~3,000개
- 수집 시점: 상품 등록 시 1회만 크롤링, 주기적 재크롤링 없음
- 수집 대상: Gmarket 스타배송 검색 결과 전체
- 등록 방식: 검색 결과 전체를 일괄 등록한 뒤, 불필요한 상품은 관리자가 직접 삭제
- 가격: **쿠폰적용가**를 `market_price`로 저장
- 중복: `order_url` 기준 upsert, 가격 이력 추가
- 자동 수집 필드: 상품명, 쿠폰적용가, 대표이미지, 상품 URL, 브랜드
- 선택 입력 필드: 제조사, 모델명, 상세설명, 키워드, 단위가격 정보
- 상세설명 자동 수집: 하지 않음
- 기준 엑셀: 서버에 최신본 1개 유지, 필요 시 교체
- 출력 엑셀: 임시 생성, 다운로드 후 관리자가 삭제 가능, DB에서 재생성 가능
- 기존 CLI(`db-import`, `db-export`, 직접 변환)는 유지

## 이번 단계 범위

- Flask + Jinja/HTMX 웹 앱
- 단일 관리자 로그인, CSRF, 세션
- Gmarket 검색 URL 검증 및 Playwright 기반 검색 결과 수집
- 검색 결과 전체를 기존 `import_crawl`로 일괄 등록
- 크롤 xlsx 업로드 fallback
- 상품 목록·검색·필터·상세·수정·삭제
- 가격 비교 화면
- 기준 엑셀 업로드/교체
- DB → 설정/최종 xlsx 생성, 다운로드, 임시 파일 삭제
- LXC 배포 구성(systemd, Caddy, SQLite 백업)
- 테스트와 실제 Gmarket 1회 수동 검증

## 이번 단계 비목표

- 상품 상세 페이지 자동 수집
- Cloudflare 우회
- 주기적 크롤링/가격 변동 알람
- 경쟁 상품 가격 수집
- 다중 사용자/권한 관리
- 상품고시/상세페이지/묶음 이미지 생성
- MySQL/PostgreSQL 전환
- 모바일 앱/외부 API
- 검색 결과에서 상품을 골라 등록하는 선택 UI
- `template` 시트 수정

## 기존 시스템

현재 저장소에는 웹과 크롤러가 없다. 다음만 존재한다.

- `playauto/db.py`: SQLite 스키마, 크롤 xlsx 로더, upsert import, 가격 이력, export 조회/검증
- `playauto/db_export.py`: setting 시트 생성, `export_from_db`
- `playauto/db_cli.py`, `run_converter.py`: `db-import`, `db-export`
- `playauto/xlsx.py`, `playauto/phase1.py`: 기존 Playauto 변환
- `playauto/constants.py`: 상품분류/수수료/헤더
- `tests/`: 55개 unittest

DB는 `data/playauto.db`이며 `products`, `listings`, `price_history`, `import_batches`가 이미 있다. `listings.active=1`만 export 대상이다. `margin_rate`는 nullable이며 blank 크롤 값은 기본 마진으로 대체된다.

## 전체 구조

```text
[Browser]
   |
   v
[Caddy] -> [Gunicorn: Flask web] -> [SQLite WAL] <- [crawl worker]
                                      |                 |
                                      |                 +-> [Playwright Chromium]
                                      |                        -> Gmarket search
                                      |
                                      +-> [data/reference/current.xlsx]
                                      +-> [data/exports/<id>/...]
```

- 웹 프로세스는 요청 처리와 화면 렌더링만 담당한다.
- 크롤링은 별도 worker 프로세스가 `crawl_jobs`를 폴링해 수행한다. Chromium이 웹 프로세스를 막지 않게 한다.
- SQLite는 WAL 모드로 웹과 worker가 동시에 읽고 쓴다. 쓰기는 짧게 유지한다.
- export는 2~3천 행 규모에서 동기 요청으로 처리한다. 오래 걸리면 이후 job으로 전환할 수 있게 함수 경계를 분리한다.

## 구성 요소

### 웹 앱 `playauto/web/app.py`

- `create_app(config=None)` 팩토리
- Flask session 기반 로그인
- Jinja 템플릿 + vendored HTMX
- 요청마다 SQLite 연결 1개, 응답 후 close
- 정적 파일은 인증 없이 제공, 나머지는 로그인 필요

### 크롤 worker `playauto/web/worker.py`

- `python -m playauto.web.worker`로 실행
- 2초 간격으로 `crawl_jobs`에서 `queued` 1건 claim
- `search` job은 Playwright로 수집, `xlsx` job은 업로드 파일을 로드
- 진행 상황을 `crawl_jobs`에 갱신
- 성공 시 `import_crawl` 결과를 job에 기록
- 실패 시 `status='failed'`, `error`에 사용자용 메시지 기록
- 오래된 export 디렉터리 정리(기본 24시간)

### 크롤러 `playauto/web/crawler.py`

- `fetch_search_cards(search_url) -> list[dict]`
- Playwright Chromium, headless, `ko-KR`, `Asia/Seoul`
- persistent context `data/browser-profile`로 쿠키 유지
- 검색 결과 카드 `.box__itemcard`가 나타날 때까지 대기
- 카드에서 다음을 추출
  - `href`: `a.link__itemcard[href]`
  - `name`: `.item_name`에서 `.box__brand`를 제거한 텍스트
  - `brand`: `.text__brand`
  - `image_url`: `.item_image img`의 `src`를 절대 URL로 변환
  - `market_price`: `.box__price .text__value`의 숫자
- 페이지네이션은 다음 페이지 버튼이 없을 때까지 진행한다. 최대 50페이지/5,000행에서 중단한다.
- Cloudflare/봇 차단 감지 시 `CrawlBlockedError`를 발생시키고 우회하지 않는다.
- DOM 추출은 page context의 JS가 raw dict 배열을 만들고, Python의 `normalize_cards`가 가격/URL/브랜드를 정규화한다. 정규화는 fixture로 단위 테스트한다.

### exporter `playauto/web/export_service.py`

- 기존 `export_from_db`를 호출한다.
- 출력 디렉터리는 `data/exports/<YYYYMMDD-HHMMSS>-<short-id>/`
- 결과 파일 경로와 다운로드 URL을 반환한다.
- reference가 없거나 `setting`/`template` 시트가 없으면 export를 막고 설정 화면으로 안내한다.

### DB 확장 `playauto/db.py`

- `SCHEMA_VERSION`을 2로 올린다.
- 기존 테이블은 변경하지 않고 `app_settings`, `crawl_jobs`만 추가한다.
- `delete_product(conn, product_id)`를 추가한다.
- 기존 `import_crawl`을 그대로 재사용한다.

## 데이터 모델 변경

### `app_settings`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `key` | TEXT PK | 설정 키 |
| `value` | TEXT NOT NULL | 값 |
| `updated_at` | TEXT NOT NULL | ISO 시각 |

키:

- `default_category_code` (기본 `기타재화[35]`)
- `default_margin` (기본 `0.15`)
- `commission_gmarket` (기본 `12.0`)
- `commission_smartstore` (기본 `6.0`)
- `commission_coupang` (기본 `10.0`)
- `reference_original_name`
- `reference_uploaded_at`
- `reference_sha256`

### `crawl_jobs`

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | INTEGER PK | job ID |
| `created_at` | TEXT NOT NULL | 생성 시각 |
| `started_at` | TEXT | 시작 시각 |
| `finished_at` | TEXT | 종료 시각 |
| `status` | TEXT NOT NULL | `queued`, `running`, `succeeded`, `failed` |
| `source` | TEXT NOT NULL | `search` 또는 `xlsx` |
| `search_url` | TEXT | 검색 URL |
| `xlsx_path` | TEXT | 업로드 xlsx 임시 경로 |
| `category_code` | TEXT NOT NULL | import 카테고리 |
| `margin` | REAL NOT NULL | 기본 마진 |
| `page_count` | INTEGER NOT NULL DEFAULT 0 | 수집 페이지 수 |
| `row_count` | INTEGER NOT NULL DEFAULT 0 | 카드 수 |
| `inserted_count` | INTEGER NOT NULL DEFAULT 0 | 신규 상품 수 |
| `updated_count` | INTEGER NOT NULL DEFAULT 0 | 갱신 상품 수 |
| `skipped_count` | INTEGER NOT NULL DEFAULT 0 | 건너뛴 행 수 |
| `import_batch_id` | INTEGER | `import_batches.id` |
| `error` | TEXT | 사용자용 오류 |
| `worker_pid` | INTEGER | 실행 worker PID |

인덱스: `INDEX(status, id)`.

### 삭제 정책

- 상품 삭제는 **hard delete**다.
- 한 트랜잭션에서 `price_history`, `listings`, `products`를 삭제한다.
- 삭제 확인 모달을 반드시 거친다.
- 상품 목록에서 체크박스로 여러 개를 선택해 일괄 삭제할 수 있다.
- 삭제된 상품은 export 대상에서 자동 제외된다.
- 가격 이력도 함께 삭제된다. 이는 “등록 후 정리” 흐름을 단순하게 유지하기 위한 결정이다.

## 크롤링 흐름

1. 관리자가 검색 URL, 카테고리, 기본 마진을 입력한다.
2. 웹은 URL을 검증한다.
   - scheme: `https`
   - host: `www.gmarket.co.kr`
   - path: `/n/stardelivery/search`
   - query: `keyword` 존재
3. `crawl_jobs`에 `queued` 행을 만든다.
4. worker가 job을 claim하고 `running`으로 바꾼다.
5. Playwright가 검색 페이지를 열고 카드가 렌더링될 때까지 기다린다.
6. 각 카드에서 이름·브랜드·쿠폰적용가·이미지·URL을 추출한다.
7. 다음 페이지가 있으면 이동해 반복한다.
8. `source_seq`는 job 전체에서 1부터 증가하는 순번으로 부여한다.
9. `CrawlData`를 만들어 `import_crawl(conn, crawl, category_code, margin, search_url)`을 호출한다.
10. 결과 counts와 `import_batch_id`를 job에 기록하고 `succeeded`로 바꾼다.
11. 화면은 job 상태를 폴링해 진행 페이지/행 수와 결과를 보여준다.

### 카드 정규화 규칙

- `name`: `.item_name` 텍스트에서 `공식`, `상품`, 브랜드 prefix를 제거하고 공백을 정리한다.
- `brand`: `.text__brand`가 있으면 저장, 없으면 `None`.
- `market_price`: `.box__price .text__value`의 `,`와 `원`을 제거해 정수화한다.
- `image_url`: `//`로 시작하면 `https:`를 붙인다.
- `order_url`: `https://item.gmarket.co.kr/Item?goodscode=...` 형태를 유지한다.
- 같은 job 안에서 URL이 중복되면 마지막 카드가 남는다.
- 필수 값(이름/가격/이미지/URL)이 없는 카드는 건너뛰고 `skipped`에 누적한다.
- 유효 카드가 0개면 job을 실패 처리한다.

### 차단/실패 처리

- 다음 중 하나면 `CrawlBlockedError`로 실패 처리한다.
  - HTTP 403/429/503
  - 제목/본문에 `Just a moment`, `Verify you are human`, `Cloudflare` 포함
  - 30초 대기 후 `.box__itemcard`가 0개
- 사용자 메시지: “Gmarket이 자동 접속을 차단했습니다. 크롤 xlsx를 업로드하거나 잠시 후 다시 시도하세요.”
- 차단 우회, CAPTCHA 자동 해결, 프록시 회전은 구현하지 않는다.

### xlsx fallback

- 웹에서 기존 크롤 xlsx를 업로드할 수 있다.
- 업로드 파일은 `data/uploads/<uuid>.xlsx`에 저장하고, job 성공/실패 후 삭제한다.
- `load_crawl_rows` + `import_crawl`을 그대로 사용한다.
- 검색 크롤과 동일한 job 상태/결과 화면을 공유한다.

## 웹 화면

### `/login`

- 비밀번호 1개 입력
- 성공 시 session 생성, dashboard로 이동
- 5회/분 실패 제한(프로세스 메모리)

### `/` dashboard

- 활성 상품 수, 활성 listing 수, 최근 job 5개, 최근 export 5개
- “검색 결과 등록”, “xlsx 업로드”, “상품 목록”, “엑셀 생성” 링크

### `/imports`

- 검색 URL 입력
- 카테고리 선택(기존 `PRODUCT_CODE_META` 키)
- 기본 마진 입력(기본 0.15)
- “등록 시작” 버튼
- 최근 job 목록: 상태, 검색어, 페이지/행 수, 신규/갱신, 오류, 재시도
- 실행 중 job은 HTMX polling으로 갱신
- “크롤 xlsx 업로드” 탭

### `/products`

- 필터: 이름/브랜드/판매자코드/URL 검색, 카테고리, 브랜드, 가격 범위
- 정렬: 최근 등록, 이름, 쿠폰적용가, 브랜드
- 페이지당 50개
- 컬럼: 이미지, 상품명, 브랜드, 쿠폰적용가, 마진율, 계산 판매가, 최근 수집일, 선택
- 행 클릭 시 상세
- 선택 삭제 버튼

### `/products/<id>`

- 기본상품 편집: 이름, 카테고리, 브랜드, 제조사, 모델명, 키워드, 상세설명
- listing 편집: 판매자코드, 판매명, 마진율, 단위가격 5개 필드
- 가격 이력 표: 관측 시각, 가격, batch
- 삭제 버튼
- 저장 시 `updated_at` 갱신
- `order_url`은 읽기 전용

### `/compare`

- 활성 listing을 상품과 join해 표시
- 컬럼: 이미지, 상품명, 브랜드, 쿠폰적용가, 용량당 가격, 마진율, Gmarket/스마트스토어/쿠팡 계산 판매가
- 정렬: 쿠폰적용가, 용량당 가격, 계산 판매가
- 용량당 가격은 `개당 용량`이 숫자+단위로 파싱될 때만 계산한다.
  - `ml`, `g`는 100ml/100g 기준으로 환산
  - `개`는 1개 기준
  - 파싱 불가면 `-`
- 상품명 클릭 시 상세의 가격 이력으로 이동

### `/exports`

- 기준 엑셀 상태 표시(파일명, 업로드 시각, 해시 앞 12자)
- 기준 엑셀 업로드/교체
- export 폼: 상품분류 옵션, 날짜, 쿠팡 단일 여부, 수수료 3종
- “엑셀 생성” 버튼
- 최근 export 목록: 생성 시각, 파일명, 다운로드, 삭제
- 기준 엑셀이 없으면 생성 버튼 비활성화

### `/settings`

- 기본 카테고리, 기본 마진, 수수료 기본값
- 기준 엑셀 정보
- export 보관 기간(기본 24시간)
- 관리자 비밀번호는 환경변수로만 관리하며 화면에서 변경하지 않는다.

## 가격 비교 의미

이번 설계에서는 가격 비교를 다음으로 정의한다.

- **서로 다른 등록 상품의 쿠폰적용가를 나란히 비교**
- 용량이 파싱되면 **100ml/100g/개당 가격**으로 비교
- 각 상품 상세에서 **과거 수집 가격 이력**을 표로 확인
- 경쟁사/다른 마켓 가격은 수집하지 않는다.

같은 상품의 과거 가격 변화만을 주 목적으로 한다면 `/compare`는 상품별 이력 중심으로 단순화할 수 있다. 구현 전에 이 정의를 확인한다.

## Export와 파일 수명

1. 기준 엑셀은 `data/reference/current.xlsx`에 1개만 둔다.
2. 업로드 시 `setting`, `template` 시트 존재를 검증하고 임시 파일에 저장한 뒤 `os.replace`로 교체한다.
3. export 시 `export_from_db`가 setting 복사본과 최종 `_단일/_일반` 또는 `_쿠팡` 파일을 만든다.
4. 출력은 `data/exports/<id>/`에 둔다.
5. 웹은 파일 다운로드 링크와 “삭제” 버튼을 제공한다.
6. worker가 시작 시 그리고 1시간마다 24시간 지난 export 디렉터리를 삭제한다.
7. export 결과는 DB에서 언제든 다시 만들 수 있다.

## 인증과 보안

- 단일 관리자 비밀번호는 `ADMIN_PASSWORD_HASH` 환경변수(Werkzeug hash)로 둔다.
- `SECRET_KEY`는 환경변수로 둔다.
- session cookie: `HttpOnly`, `SameSite=Lax`, HTTPS에서는 `Secure`.
- 모든 POST에 CSRF 토큰을 요구한다. 토큰은 session에 저장하고 hidden input으로 렌더링한다.
- 로그인 실패 rate limit: 프로세스 메모리 기준 5회/분.
- 업로드 최대 20MB, 확장자 `.xlsx`만 허용, 저장 파일명은 UUID로 바꾼다.
- 검색 URL은 Gmarket 스타배송 검색 URL만 허용한다.
- 외부 공개 시 Caddy HTTPS를 전제로 한다. 도메인이 없으면 LAN/Tailscale 바인딩만 사용한다.
- 상세 페이지/Cloudflare 우회는 하지 않는다.

## 배포

### LXC 권장 사양

- 디스크 40GB
- 최소 2 vCPU / 4GB RAM
- Chromium 크롤링을 고려하면 **4 vCPU / 8GB RAM 권장**
- unprivileged LXC
- Ubuntu 24.04 기준

### 의존성

- Python 3.12
- Flask 3.x
- gunicorn
- Playwright + Chromium
- HTMX는 `static/htmx.min.js`로 vendoring
- 기존 `openpyxl`은 `vendor/`를 그대로 사용
- `requirements-web.txt`에 Flask/gunicorn/playwright 버전을 고정
- LXC에서 `playwright install --with-deps chromium` 실행

### 서비스

- `playauto-web.service`
  - `gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8000 "playauto.web.app:create_app()"`
- `playauto-worker.service`
  - `python -m playauto.web.worker`
  - `After=playauto-web.service`
- Caddy: `reverse_proxy 127.0.0.1:8000`
- 데이터 디렉터리
  - `data/playauto.db`
  - `data/reference/`
  - `data/exports/`
  - `data/uploads/`
  - `data/browser-profile/`

### 백업

- 일 1회 `sqlite3 data/playauto.db ".backup ..."`로 DB 백업
- 기준 엑셀과 백업 파일은 별도 경로에 보관
- export 임시 파일은 백업하지 않는다.

## 오류 처리

- 검색 URL 형식 오류: 폼 필드 오류로 즉시 표시
- 기준 엑셀 시트 누락: `필수 시트 누락: [...]`를 화면에 표시
- export 필수 값 누락: 기존 `listing id=...` 메시지를 그대로 표시
- Gmarket 차단: job `failed` + fallback 안내
- Playwright/Chromium 실행 실패: job `failed` + worker 로그 확인 안내
- DB locked: `busy_timeout=5000` 후 사용자에게 재시도 안내
- worker가 비정상 종료해 `running`이 30분 이상 지속: 목록에서 “중단됨”으로 표시하고 재시도 버튼 제공

## 테스트 전략

### 단위 테스트

- `normalize_cards`: 이름/브랜드/가격/이미지/URL 정규화, 중복 URL, 빈 카드
- `validate_search_url`: 허용/거부 URL
- `delete_product`: products/listings/price_history가 함께 삭제되고 다른 상품은 유지
- `claim_next_job`: queued만 claim, running/terminal은 제외
- `parse_capacity`: ml/g/개, 파싱 불가
- `compute_unit_price`: 100ml/100g/개 기준
- 설정 키 기본값/업데이트
- 기존 v1 DB에 `ensure_schema`를 적용하면 `app_settings`/`crawl_jobs`가 추가되고 `user_version=2`가 되는지
- export 서비스: reference 누락, 정상 생성, 파일명

### 웹 테스트(Flask test client)

- 로그인 없이 접근 시 `/login`으로 이동
- 로그인/로그아웃, CSRF 실패
- 상품 목록 필터/페이지네이션
- 상품 수정/삭제
- xlsx fallback import(임시 xlsx, worker 대신 동기 함수 호출)
- export 폼과 다운로드

### 수동 검증

- 실제 Gmarket 카프리썬 검색 URL로 job 실행
- 카드 수, 가격, 브랜드, URL 확인
- 같은 URL 재등록 시 가격 이력 추가 및 사용자 편집값 보존 확인
- Cloudflare 차단 시 실패 메시지와 xlsx fallback 확인
- LXC에서 export → 다운로드 → 삭제 → 재생성 확인
- 기존 55개 unittest 통과

## 파일/함수 설계

```text
playauto/web/
  __init__.py
  app.py              create_app, login/logout, CSRF
  config.py           env/config dataclass
  auth.py             password check, login_required
  routes.py           dashboard/imports/products/compare/exports/settings
  queries.py          product/list/job/export queries
  crawler.py          search URL validation, Playwright fetch, normalize_cards
  worker.py           job polling, claim, run, cleanup
  export_service.py   export_from_db wrapper, download/delete
  templates/
    base.html
    login.html
    dashboard.html
    imports.html
    products.html
    product_detail.html
    compare.html
    exports.html
    settings.html
  static/
    htmx.min.js
    app.css
    app.js
tests/
  test_web_auth.py
  test_web_products.py
  test_web_jobs.py
  test_web_crawler.py
  test_web_export.py
```

### `playauto/db.py` 추가

- `SCHEMA_VERSION = 2`
- `SCHEMA_SQL`에 `app_settings`, `crawl_jobs` 추가
- `delete_product(conn, product_id) -> bool`
- `connect()`는 기존 그대로 두고 web/worker에서 WAL/busy_timeout을 설정

### `run_converter.py`

- 기존 DB/직접 변환 dispatch 유지
- 웹은 `python -m playauto.web.app` 또는 gunicorn으로 실행하며 `run_converter.py`에 섞지 않는다.

## 완료 기준

- 관리자가 로그인해 검색 URL을 등록하면 검색 결과 전체가 DB에 들어간다.
- 같은 URL을 다시 등록하면 중복 상품이 생기지 않고 가격 이력만 추가된다.
- 상품 목록에서 불필요한 상품을 단건/일괄 삭제할 수 있다.
- 상품 상세에서 마진율·메타데이터를 수정할 수 있다.
- 가격 비교 화면에서 쿠폰적용가와 계산 판매가를 비교할 수 있다.
- 기준 엑셀을 교체하고, DB에서 설정/최종 xlsx를 생성·다운로드·삭제할 수 있다.
- Gmarket 차단 시 xlsx 업로드로 같은 등록 흐름을 사용할 수 있다.
- 기존 CLI와 55개 테스트가 깨지지 않는다.
- LXC에서 web/worker가 systemd로 자동 시작되고 재부팅 후에도 동작한다.

## 위험과 대응

- **Gmarket/Cloudflare 차단**: 검색 페이지도 LXC IP에서 차단될 수 있다. persistent profile, headless Chromium, fallback xlsx를 둔다. 우회는 하지 않는다.
- **Chromium 메모리**: 4GB에서는 빠듯할 수 있어 8GB 권장. job은 1개만 동시 실행한다.
- **SQLite 동시 쓰기**: WAL + busy_timeout + worker 1개로 제한한다.
- **2~3천 행 export 시간**: 동기 요청이 길어지면 job 전환. 현재 규모에서는 동기로 시작한다.
- **기준 엑셀 변경**: 업로드 시 시트 검증, 교체는 원자적으로 수행한다.
- **원격 노출 보안**: HTTPS 없는 공개 노출을 금지하고, 강한 비밀번호/CSRF/세션 설정을 적용한다.
- **상세 필드 부재**: 브랜드만 자동 수집되고 제조사/모델명은 수동 입력이다. 필요하면 이후 상세 페이지 수집을 별도 단계로 둔다.

## 확인이 필요한 가정

1. 가격 비교는 “서로 다른 상품의 쿠폰적용가/용량당 가격 + 상품별 가격 이력”으로 본다.
2. 관리자는 1명이며 사용자 관리 화면은 두지 않는다.
3. 상품 삭제는 hard delete로 하고 가격 이력도 함께 삭제한다.
4. 카테고리는 import 단위로 1개 선택하며 기본값을 설정에 저장한다.
5. 검색 결과는 페이지 끝까지 전부 등록하고, 선택 등록 UI는 두지 않는다.
6. LXC는 4 vCPU/8GB를 권장하고, 도메인이 없으면 LAN/Tailscale로만 노출한다.
7. 제조사/모델명은 자동 수집하지 않고 상세 화면에서 수동 입력한다.
