# 상세페이지 기반 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품별 상세페이지 제목·마케팅 문구·주의사항·추가 이미지·고시 이미지·11번가 URL을 저장하고, 폭 860px JPG를 생성해 미리보기하며, 엑셀 `상세설명`에 11번가 URL을 내보낸다.

**Architecture:** 기존 Flask 상품 상세 화면에 `상세페이지` 탭을 추가한다. 상세페이지 HTML은 순수 파이썬 함수로 만들고, Playwright가 HTML을 JPEG로 렌더링한다. DB에는 JPG 경로가 아니라 11번가 URL만 영구 저장한다. 모델 DB·Gemini·11번가 자동 업로드는 후속 계획으로 분리한다.

**Tech Stack:** Flask 3.1, SQLite, Jinja2, Playwright 1.50, openpyxl, unittest.

**Spec:** 2026-11-01 대화에서 확정한 상세페이지 사양. 이 계획의 `Global Constraints`가 그 결정을 고정한다.

## Global Constraints

- 상세페이지 이미지 폭은 `860px`, JPG 품질은 `90`이다.
- 제목 기본값은 `product.name`이며 수정 가능하고, 화면에서는 최대 2줄이다.
- 추가 이미지는 기본 이미지와 고시 이미지 사이에 최대 5장만 들어간다.
- 고시 이미지는 상세페이지 생성에 필수다. 없으면 생성은 명확한 오류로 실패한다.
- 주의사항이 비어 있으면 공통 기본 문구 `상품의 상세 정보와 유통기한, 보관 방법을 확인해 주세요.`를 쓴다. 카테고리별 법정 안내문 원문은 사용자 제공 후 상수로 교체한다.
- 배경·강조 색상은 생성할 때마다 검증된 팔레트에서 무작위로 고른다. 테스트에서는 시드를 고정한다.
- JPG는 장기 저장하지 않는다. DB에는 `detail_page_url`(11번가 URL)만 영구 저장한다.
- 엑셀 `상세설명` 열은 `detail_page_url`이 있으면 그 URL, 없으면 기존 `detail`을 쓴다.
- 이 계획에는 Gemini, 모델 DB, 11번가 자동 업로드, 추가 이미지 크롤링을 넣지 않는다.
- 기존 v2 DB를 데이터 손실 없이 v3로 마이그레이션한다.
- 모든 사용자 입력 텍스트는 HTML로 렌더링할 때 이스케이프한다.

## Review Focus

- 40자를 넘는 상품명이 제목 2줄을 넘어 레이아웃을 깨뜨릴 수 있다. 제목 길이별 폰트 축소와 2줄 클램프를 테스트한다.
- 고시 이미지 URL이 비어 있으면 생성이 반쯤 된 JPG를 만들 수 있다. 생성 전 필수 검증을 테스트한다.
- 잘못된 이미지 URL이나 응답 없는 URL에서 Playwright가 멈출 수 있다. `set_content`에 `wait_until="load"`, `timeout=15000`을 고정하고 테스트한다.
- 제목·문구·주의사항에 `<script>`가 들어오면 상세페이지 HTML에 그대로 실행될 수 있다. 이스케이프 테스트를 둔다.
- 기존 v2 DB에 새 컬럼이 없으면 상품 상세가 500으로 깨진다. v2 DB 마이그레이션과 데이터 보존을 테스트한다.

## File Structure

- `playauto/db.py`: v3 스키마, `migrate_schema()`, `ExportRow`에 `detail_page_url` 추가.
- `playauto/detail_page.py`: 팔레트, 제목 크기, 상세페이지 HTML 생성. 순수 함수만 둔다.
- `playauto/web/detail_page_image.py`: Playwright로 HTML을 JPG로 렌더링.
- `playauto/web/detail_page_service.py`: 폼 파싱, 저장, 생성 오케스트레이션.
- `playauto/web/queries.py`: 상세페이지 필드 조회/수정.
- `playauto/web/routes.py`: 상세페이지 탭, 저장, 생성, 미리보기 라우트.
- `playauto/web/templates/product_detail.html`: 탭과 상세페이지 폼.
- `playauto/web/static/app.css`: 탭, 미리보기, 상세페이지 폼 스타일.
- `playauto/db_export.py`: `상세설명`에 `detail_page_url` 우선 사용.
- `tests/test_db.py`, `tests/test_detail_page.py`, `tests/test_detail_page_image.py`, `tests/test_detail_page_service.py`, `tests/test_web_detail_page.py`, `tests/test_db_export.py`.

---

### Task 1: v3 스키마와 마이그레이션

**Files:**
- Modify: `playauto/db.py:11`, `playauto/db.py:40-56`, `playauto/db.py:284-288`
- Test: `tests/test_db.py:65-79`

**Interfaces:**
- Produces: `SCHEMA_VERSION = 3`
- Produces: `migrate_schema(conn: sqlite3.Connection) -> None`
- Produces: `products` 컬럼 `detail_page_title`, `detail_page_marketing`, `detail_page_caution`, `detail_page_extra_images`, `notice_image_url`, `detail_page_url`, `detail_page_updated_at`

- [ ] **Step 1: Write the failing test**

```python
def test_migrate_v2_db_adds_detail_page_columns_and_preserves_rows(self):
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "test.db")
        conn.executescript("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_seq INTEGER NOT NULL,
            name TEXT NOT NULL,
            image_url TEXT NOT NULL,
            order_url TEXT NOT NULL UNIQUE,
            category_code TEXT NOT NULL,
            detail TEXT,
            keywords TEXT,
            manufacturer TEXT,
            brand TEXT,
            model TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL,
            last_batch_id INTEGER
        );
        INSERT INTO products (source_seq, name, image_url, order_url,
            category_code, last_seen_at)
        VALUES (1, '기존 상품', 'img', 'https://order/1', 'C1', 'now');
        """)
        ensure_schema(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        self.assertTrue({
            "detail_page_title", "detail_page_marketing", "detail_page_caution",
            "detail_page_extra_images", "notice_image_url", "detail_page_url",
            "detail_page_updated_at",
        } <= columns)
        self.assertEqual(
            conn.execute("SELECT name FROM products").fetchone()["name"], "기존 상품"
        )
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_db.DbSchemaTests.test_migrate_v2_db_adds_detail_page_columns_and_preserves_rows -v`
Expected: FAIL because `ensure_schema` does not add the columns and user_version is 2.

- [ ] **Step 3: Implement schema changes**

`SCHEMA_VERSION = 3`. Add the seven columns to the `products` table in `SCHEMA_SQL`. Add `migrate_schema(conn)` that reads `PRAGMA table_info(products)` and runs `ALTER TABLE products ADD COLUMN ...` for each missing column. Call it from `ensure_schema()` after `executescript(SCHEMA_SQL)` and before setting `PRAGMA user_version=3`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_db -v`
Expected: PASS, including the existing schema version assertion updated from 2 to 3.

- [ ] **Step 5: Commit**

```bash
git add playauto/db.py tests/test_db.py
git commit -m "feat: add detail page schema migration"
```

---

### Task 2: 상세페이지 HTML 생성

**Files:**
- Create: `playauto/detail_page.py`
- Test: `tests/test_detail_page.py`

**Interfaces:**
- Produces: `Palette` dataclass with `background`, `surface`, `accent`, `text`
- Produces: `PALETTES: tuple[Palette, ...]`
- Produces: `pick_palette(seed: int | None = None) -> Palette`
- Produces: `title_font_size(title: str) -> int`
- Produces: `DEFAULT_CAUTION_TEXT = "상품의 상세 정보와 유통기한, 보관 방법을 확인해 주세요."`
- Produces: `build_detail_page_html(*, title: str, marketing: str, caution: str, main_image_url: str, extra_image_urls: list[str], notice_image_url: str, palette: Palette) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_detail_page_html_escapes_user_text_and_orders_images(self):
    html = build_detail_page_html(
        title="<script>alert(1)</script>",
        marketing="신선한 주스",
        caution="유통기한을 확인하세요",
        main_image_url="https://img/main.jpg",
        extra_image_urls=["https://img/1.jpg", "https://img/2.jpg"],
        notice_image_url="https://img/notice.jpg",
        palette=PALETTES[0],
    )
    self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
    self.assertNotIn("<script>alert(1)</script>", html)
    self.assertLess(html.index("https://img/main.jpg"), html.index("https://img/1.jpg"))
    self.assertLess(html.index("https://img/2.jpg"), html.index("https://img/notice.jpg"))
    self.assertIn("width: 860px", html)
    self.assertIn("-webkit-line-clamp: 2", html)

def test_build_detail_page_html_uses_default_caution_when_blank(self):
    html = build_detail_page_html(
        title="제목",
        marketing="문구",
        caution="",
        main_image_url="https://img/main.jpg",
        extra_image_urls=[],
        notice_image_url="https://img/notice.jpg",
        palette=PALETTES[0],
    )
    self.assertIn(DEFAULT_CAUTION_TEXT, html)

def test_title_font_size_shrinks_for_long_titles(self):
    self.assertEqual(title_font_size("짧은 제목"), 48)
    self.assertEqual(title_font_size("가" * 40), 36)
    self.assertEqual(title_font_size("가" * 60), 30)

def test_pick_palette_is_deterministic_with_seed(self):
    self.assertEqual(pick_palette(seed=0), pick_palette(seed=0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_detail_page -v`
Expected: FAIL because `playauto.detail_page` does not exist.

- [ ] **Step 3: Implement `playauto/detail_page.py`**

Use `html.escape` for every text value. Build one complete HTML document with inline CSS. The document must include `data-detail-page="v1"`, a title block with `-webkit-line-clamp: 2`, the main image, extra images in order, the notice image, marketing copy, caution text, and a footer. Use `title_font_size()` for the title. Use the palette values as CSS colors. Do not add JavaScript.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_detail_page -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add playauto/detail_page.py tests/test_detail_page.py
git commit -m "feat: render detail page html"
```

---

### Task 3: Playwright JPEG 렌더러

**Files:**
- Create: `playauto/web/detail_page_image.py`
- Test: `tests/test_detail_page_image.py`

**Interfaces:**
- Produces: `render_html_to_jpeg(html: str, output_path: Path, *, width: int = 860, quality: int = 90) -> Path`

- [ ] **Step 1: Write the failing test with a fake Playwright**

```python
def test_render_html_to_jpeg_uses_fixed_jpeg_settings(self):
    calls = {}
    class FakePage:
        def set_viewport_size(self, size): calls["viewport"] = size
        def set_content(self, html, **kwargs): calls["content"] = (html, kwargs)
        def screenshot(self, **kwargs): calls["screenshot"] = kwargs
    class FakeBrowser:
        def new_page(self): return FakePage()
        def close(self): calls["closed"] = True
    class FakeChromium:
        def launch(self, headless): calls["headless"] = headless; return FakeBrowser()
    class FakePlaywright:
        chromium = FakeChromium()
    class FakeCM:
        def __enter__(self): return FakePlaywright()
        def __exit__(self, *args): return False
    with tempfile.TemporaryDirectory() as tmp:
        with patch(
            "playauto.web.detail_page_image.sync_playwright",
            return_value=FakeCM(),
        ):
            output = render_html_to_jpeg("<html></html>", Path(tmp) / "out.jpg")
        self.assertEqual(output, Path(tmp) / "out.jpg")
    self.assertEqual(calls["viewport"], {"width": 860, "height": 1000})
    self.assertEqual(calls["content"][1], {"wait_until": "load", "timeout": 15000})
    self.assertEqual(calls["screenshot"]["type"], "jpeg")
    self.assertEqual(calls["screenshot"]["quality"], 90)
    self.assertTrue(calls["screenshot"]["full_page"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_detail_page_image -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement `render_html_to_jpeg`**

Create the output parent directory. Launch Chromium headless. Set viewport `{"width": width, "height": 1000}`. Call `set_content(html, wait_until="load", timeout=15000)`. Call `screenshot(path=str(output_path), full_page=True, type="jpeg", quality=quality)`. Close the browser in `finally`. Return the output path.

- [ ] **Step 4: Run test**

Run: `python -m unittest tests.test_detail_page_image -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add playauto/web/detail_page_image.py tests/test_detail_page_image.py
git commit -m "feat: render detail page jpeg with playwright"
```

---

### Task 4: 상세페이지 저장·생성 서비스

**Files:**
- Create: `playauto/web/detail_page_service.py`
- Modify: `playauto/web/queries.py:30-48`, `playauto/web/queries.py:139-157`
- Test: `tests/test_detail_page_service.py`

**Interfaces:**
- Produces: `parse_detail_page_form(form) -> dict`
- Produces: `save_detail_page(conn, product_id: int, values: dict) -> None`
- Produces: `generate_detail_page(conn, product_id: int, *, renderer=render_html_to_jpeg, palette_seed: int | None = None) -> Path`
- Produces: `DETAIL_PAGE_DIR = Path("data/detail-pages")`

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_detail_page_form_caps_extra_images_at_five(self):
    values = parse_detail_page_form({
        "detail_page_title": "제목",
        "detail_page_marketing": "문구",
        "detail_page_caution": "주의",
        "detail_page_extra_images": "a\nb\nc\nd\ne\nf",
        "notice_image_url": "https://img/notice.jpg",
        "detail_page_url": "https://11st/url",
    })
    self.assertEqual(values["detail_page_extra_images"], ["a", "b", "c", "d", "e"])

def test_generate_detail_page_requires_notice_image(self):
    with self.assertRaisesRegex(ValueError, "고시 이미지"):
        generate_detail_page(self.conn, self.pid)

def test_generate_detail_page_uses_renderer_and_returns_path(self):
    seen = {}
    def fake_renderer(html, output_path):
        seen["html"] = html
        output_path.write_bytes(b"jpeg")
        return output_path
    path = generate_detail_page(
        self.conn, self.pid, renderer=fake_renderer, palette_seed=0
    )
    self.assertEqual(path, DETAIL_PAGE_DIR / f"{self.pid}.jpg")
    self.assertIn("상품1", seen["html"])
    self.assertTrue(path.exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_detail_page_service -v`
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the service and query fields**

`parse_detail_page_form` strips text, splits extra images on newlines/commas, drops blanks, and keeps the first 5. `save_detail_page` serializes extra images with `json.dumps(..., ensure_ascii=False)` into `detail_page_extra_images`, updates the seven product columns, and sets `detail_page_updated_at` to the current UTC ISO string. `generate_detail_page` loads the product, parses `detail_page_extra_images` JSON back to a list, raises `ValueError("고시 이미지가 필요합니다.")` when `notice_image_url` is blank, calls `build_detail_page_html`, and writes to `DETAIL_PAGE_DIR / f"{product_id}.jpg"`. The preview file is overwritten on each generation; no preview path is stored in the DB. Add the seven fields to `PRODUCT_FIELDS` and `PRODUCT_SELECT` so the route can read them.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_detail_page_service -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add playauto/web/detail_page_service.py playauto/web/queries.py tests/test_detail_page_service.py
git commit -m "feat: save and generate detail pages"
```

---

### Task 5: 상세페이지 탭과 라우트

**Files:**
- Modify: `playauto/web/routes.py:246-308`, `playauto/web/templates/product_detail.html`, `playauto/web/static/app.css`
- Test: `tests/test_web_detail_page.py`

**Interfaces:**
- Consumes: `parse_detail_page_form`, `save_detail_page`, `generate_detail_page`
- Produces route functions:
  - `product_detail` (`GET /products/<int:product_id>?tab=detail`)
  - `product_detail_save` (`POST /products/<int:product_id>/detail-page`)
  - `product_detail_generate` (`POST /products/<int:product_id>/detail-page/generate`)
  - `product_detail_preview` (`GET /products/<int:product_id>/detail-page/preview`)

- [ ] **Step 1: Write the failing route tests**

```python
def test_detail_tab_renders_detail_page_fields(self):
    response = self.client.get(f"/products/{self.pid}?tab=detail")
    body = response.get_data(as_text=True)
    self.assertEqual(response.status_code, 200)
    self.assertIn("상세페이지", body)
    self.assertIn("detail_page_title", body)
    self.assertIn("detail_page_url", body)

def test_save_detail_page_route_persists_values(self):
    response = post_with_csrf(self.client, f"/products/{self.pid}/detail-page", {
        "detail_page_title": "새 제목",
        "detail_page_marketing": "새 문구",
        "detail_page_caution": "새 주의",
        "detail_page_extra_images": "https://img/1.jpg",
        "notice_image_url": "https://img/notice.jpg",
        "detail_page_url": "https://11st/url",
    })
    self.assertEqual(response.status_code, 302)
    row = self.conn.execute("SELECT * FROM products WHERE id=?", (self.pid,)).fetchone()
    self.assertEqual(row["detail_page_title"], "새 제목")
    self.assertEqual(row["detail_page_url"], "https://11st/url")

def test_generate_route_flashes_and_redirects(self):
    with patch("playauto.web.routes.generate_detail_page") as generate:
        generate.return_value = Path("data/detail-pages/1.jpg")
        response = post_with_csrf(self.client, f"/products/{self.pid}/detail-page/generate", {})
    self.assertEqual(response.status_code, 302)
    generate.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_web_detail_page -v`
Expected: FAIL with 404 or missing template fields.

- [ ] **Step 3: Implement routes and template**

Add `tab = request.args.get("tab", "info")` to the product detail route and pass it to the template. Add the save route, the generate route, and the preview route. The generate route catches `ValueError` and flashes its message, then redirects to the detail tab. The preview route uses `send_from_directory` on `DETAIL_PAGE_DIR` with the filename `f"{product_id}.jpg"`. In `product_detail.html`, render two tab links and conditionally show the existing info form or the new detail form. The detail form posts to `main.product_detail_save`, includes a preview `<img>` when `tab == "detail"`, and a separate generate form posting to `main.product_detail_generate`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_web_detail_page -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add playauto/web/routes.py playauto/web/templates/product_detail.html playauto/web/static/app.css tests/test_web_detail_page.py
git commit -m "feat: add detail page tab and routes"
```

---

### Task 6: 엑셀 `상세설명`에 11번가 URL 사용

**Files:**
- Modify: `playauto/db.py:159-193`, `playauto/db_export.py:27-50`
- Test: `tests/test_db_export.py`

**Interfaces:**
- Produces: `ExportRow.detail_page_url: str | None`
- Produces: `EXPORT_QUERY` selects `p.detail_page_url`

- [ ] **Step 1: Write the failing test**

```python
def test_write_setting_uses_detail_page_url_for_detail_column(self):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        reference = tmp / "reference.xlsx"
        output = tmp / "setting.xlsx"
        make_reference(reference)
        row = make_export_row(
            detail="기존 상세",
            detail_page_url="https://11st/detail/1",
        )
        result = write_setting_from_rows(reference, [row], output)
        ws = load_workbook(result)["setting"]
        self.assertEqual(ws["H2"].value, "https://11st/detail/1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_db_export.SettingWriterTests.test_write_setting_uses_detail_page_url_for_detail_column -v`
Expected: FAIL because `ExportRow` has no `detail_page_url`.

- [ ] **Step 3: Implement the export change**

Add `detail_page_url` to `ExportRow` and `EXPORT_QUERY`. In `_row_values`, replace `row.detail` with `row.detail_page_url or row.detail` at the `상세설명` position. Update `make_export_row` in the test helper to default `detail_page_url=None`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_db_export -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add playauto/db.py playauto/db_export.py tests/test_db_export.py
git commit -m "feat: export detail page url"
```

---

### Task 7: 실제 JPG 생성 확인

**Files:**
- No source changes.

- [ ] **Step 1: Run the full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 2: Start the app with the prototype DB and generate a real JPG**

Use the existing local DB `data/prototype.db`, set `DATABASE=data/prototype.db`, log in, open product 60, fill `notice_image_url` with a real image URL, save, click `JPG 생성`, and open the preview. Confirm the JPEG is 860px wide and visually contains the title, marketing copy, main image, extra images, notice image, and caution text.

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "test: verify detail page jpeg output"
```

---

## 후속 계획

- 모델 DB, Gemini 마케팅 문구/키워드, 복합상품 세트, 고시 이미지 자동 선택.
- 11번가 자동 업로드 어댑터와 URL 저장.
- 추가 이미지 크롤링/업로드, Gmarket headed 수동 통과 모드.
