from pathlib import Path

from playwright.sync_api import sync_playwright


def render_html_to_jpeg(
    html: str,
    output_path: Path,
    *,
    width: int = 860,
    quality: int = 90,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_viewport_size({"width": width, "height": 1000})
            page.set_content(html, wait_until="load", timeout=15000)
            page.screenshot(
                path=str(output_path),
                full_page=True,
                type="jpeg",
                quality=quality,
            )
        finally:
            browser.close()
    return output_path
