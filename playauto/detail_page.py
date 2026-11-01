import html
import random
from dataclasses import dataclass

DEFAULT_CAUTION_TEXT = (
    "상품의 상세 정보와 유통기한, 보관 방법을 확인해 주세요."
)


@dataclass(frozen=True)
class Palette:
    background: str
    surface: str
    accent: str
    text: str


PALETTES = (
    Palette("#F5F1E8", "#FFFFFF", "#1F3A2E", "#1A1A1A"),
    Palette("#EAF2F8", "#FFFFFF", "#1B4F72", "#17202A"),
    Palette("#FDF2E9", "#FFFFFF", "#A04000", "#1B1B1B"),
    Palette("#F4ECF7", "#FFFFFF", "#5B2C6F", "#1B1B1B"),
    Palette("#E8F8F5", "#FFFFFF", "#0E6251", "#1B1B1B"),
)


def pick_palette(seed: int | None = None) -> Palette:
    return random.Random(seed).choice(PALETTES)


def title_font_size(title: str) -> int:
    length = len(title.strip())
    if length <= 20:
        return 48
    if length <= 40:
        return 36
    return 30


def build_detail_page_html(
    *,
    title: str,
    marketing: str,
    caution: str,
    main_image_url: str,
    extra_image_urls: list[str],
    notice_image_url: str,
    palette: Palette,
) -> str:
    safe_title = html.escape(title, quote=True)
    safe_marketing = html.escape(marketing, quote=True)
    safe_caution = html.escape(caution or DEFAULT_CAUTION_TEXT, quote=True)
    safe_main = html.escape(main_image_url, quote=True)
    safe_notice = html.escape(notice_image_url, quote=True)
    extra_images = "".join(
        f'<img src="{html.escape(url, quote=True)}" alt="">'
        for url in extra_image_urls
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=860">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: {palette.background};
    color: {palette.text};
    font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
  }}
  .page {{ width: 860px; margin: 0 auto; background: {palette.background}; }}
  .hero {{
    padding: 56px 56px 36px;
    background: {palette.surface};
    border-bottom: 6px solid {palette.accent};
  }}
  h1 {{
    margin: 0;
    font-size: {title_font_size(title)}px;
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .marketing {{
    margin: 18px 0 0;
    font-size: 22px;
    line-height: 1.6;
    color: {palette.accent};
  }}
  .media img {{ display: block; width: 860px; height: auto; }}
  .section {{
    padding: 40px 56px;
    background: {palette.surface};
  }}
  .section h2 {{
    margin: 0 0 18px;
    font-size: 26px;
    color: {palette.accent};
  }}
  .section p {{ margin: 0; font-size: 20px; line-height: 1.7; }}
  .notice {{ padding: 0; background: {palette.background}; }}
  .footer {{
    padding: 28px 56px 48px;
    background: {palette.accent};
    color: #FFFFFF;
    font-size: 18px;
    line-height: 1.6;
  }}
</style>
</head>
<body data-detail-page="v1">
  <main class="page">
    <header class="hero">
      <h1>{safe_title}</h1>
      <p class="marketing">{safe_marketing}</p>
    </header>
    <div class="media">
      <img src="{safe_main}" alt="">
      {extra_images}
    </div>
    <div class="media notice">
      <img src="{safe_notice}" alt="">
    </div>
    <section class="section">
      <h2>꼭 확인해주세요</h2>
      <p>{safe_caution}</p>
    </section>
    <footer class="footer">상품 정보를 확인하고 안전하게 사용해 주세요.</footer>
  </main>
</body>
</html>
"""
