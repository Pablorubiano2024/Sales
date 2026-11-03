"""Makes a vertical (1080x1920) video, under a minute, for every active
MercadoLibre listing, from the listing's own photos and attributes — ML
flags listings without a video as lower quality ("Crea video para no
perder ventas").

Each video is a slideshow: the listing's photos over a blurred copy of
themselves, a slow zoom, cross-fades, the title on the first slide, one
real attribute per photo, and a closing "Envío gratis" slide (only when
the listing really has free shipping). Nothing is invented: every word
comes from the live item.

ML's clips upload endpoint answers 403 for this account (verified
2026-11-03; its docs cover only Global Selling items), so this only writes
the files — upload them from the seller panel. Output: data/videos/<item>.mp4

Usage:
    python scripts/make_listing_videos.py                  # every active listing
    python scripts/make_listing_videos.py MCO2236126911 …  # just these
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from backend.app.core.database import SessionLocal  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.marketplace import ListingStatus, MarketplaceProduct  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "videos"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
SLIDE_SECONDS, FADE_SECONDS = 4.0, 0.5
MAX_PHOTOS = 6
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
# Identifiers, not selling points.
SKIP_ATTRIBUTES = {
    "BRAND",
    "MODEL",
    "GTIN",
    "SELLER_SKU",
    "ITEM_CONDITION",
    "MPN",
    "LINE",
    "ALPHANUMERIC_MODEL",
    "EMPTY_GTIN_REASON",
    "PACKAGE_HEIGHT",
    "PACKAGE_LENGTH",
    "PACKAGE_WIDTH",
    "PACKAGE_WEIGHT",
    "SHIPMENT_PACKING",
}


def selling_points(item: dict[str, Any]) -> list[str]:
    """Short "Name: value" lines from the item's real attributes."""
    points = []
    for attr in item.get("attributes") or []:
        name, value = attr.get("name"), attr.get("value_name")
        attr_id = attr.get("id") or ""
        if attr_id in SKIP_ATTRIBUTES or "PACKAGE" in attr_id or not name or not value:
            continue
        line = f"{name}: {value}"
        if len(line) <= 42:
            points.append(line)
    return points


def _cover(photo: Image.Image) -> Image.Image:
    scale = max(WIDTH / photo.width, HEIGHT / photo.height)
    resized = photo.resize((int(photo.width * scale) + 1, int(photo.height * scale) + 1))
    left, top = (resized.width - WIDTH) // 2, (resized.height - HEIGHT) // 2
    background = resized.crop((left, top, left + WIDTH, top + HEIGHT))
    background = background.filter(ImageFilter.GaussianBlur(40))
    return Image.blend(background, Image.new("RGB", (WIDTH, HEIGHT), "black"), 0.35)


def _band(draw: ImageDraw.ImageDraw, lines: list[str], font: Any, *, top: int) -> None:
    line_height = font.size + 18
    height = line_height * len(lines) + 50
    draw.rounded_rectangle(
        (40, top, WIDTH - 40, top + height), radius=36, fill=(255, 255, 255, 235)
    )
    for i, line in enumerate(lines):
        draw.text(
            (WIDTH // 2, top + 25 + i * line_height + line_height // 2),
            line,
            font=font,
            fill=(20, 20, 20),
            anchor="mm",
        )


def trim_white(photo: Image.Image) -> Image.Image:
    """Crop the near-white margin store photos carry, keeping a little."""
    diff = ImageChops.difference(photo, Image.new("RGB", photo.size, "white")).convert("L")
    box = diff.point(lambda v: 255 if v > 18 else 0).getbbox()
    if box is None:
        return photo
    pad = int(0.04 * max(photo.size))
    left, top, right, bottom = box
    return photo.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(photo.width, right + pad),
            min(photo.height, bottom + pad),
        )
    )


def make_slide(photo: Image.Image, *, top: list[str], bottom: list[str]) -> Image.Image:
    """One 1080x1920 frame: blurred background, the photo on a white card,
    text bands above and below it."""
    photo = photo.convert("RGB")
    slide = _cover(photo).convert("RGBA")
    card = Image.new("RGB", (980, 980), "white")
    fitted = trim_white(photo)
    scale = min(920 / fitted.width, 920 / fitted.height)
    fitted = fitted.resize((int(fitted.width * scale), int(fitted.height * scale)))
    card.paste(fitted, ((980 - fitted.width) // 2, (980 - fitted.height) // 2))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *card.size), radius=40, fill=255)
    slide.paste(card, ((WIDTH - 980) // 2, 470), mask)

    overlay = Image.new("RGBA", slide.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if top:
        _band(draw, top, ImageFont.truetype(FONT_BOLD, 62), top=120)
    if bottom:
        _band(draw, bottom, ImageFont.truetype(FONT_REGULAR, 58), top=1530)
    return Image.alpha_composite(slide, overlay).convert("RGB")


def slides_for(item: dict[str, Any], photos: list[Image.Image]) -> list[Image.Image]:
    title = textwrap.wrap(item["title"], 26)[:3]
    points = selling_points(item)
    slides = [make_slide(photos[0], top=title, bottom=points[:1])]
    for i, photo in enumerate(photos[1:], start=1):
        slides.append(make_slide(photo, top=[], bottom=points[i : i + 1]))
    if (item.get("shipping") or {}).get("free_shipping"):
        slides.append(make_slide(photos[0], top=title, bottom=["Envío gratis"]))
    return slides


def render(slides: list[Image.Image], out: Path) -> None:
    """Slow zoom on each slide, cross-fades between them, H.264 MP4."""
    with tempfile.TemporaryDirectory() as tmp:
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        for i, slide in enumerate(slides):
            path = Path(tmp) / f"{i}.png"
            slide.save(path)
            args += ["-loop", "1", "-framerate", str(FPS), "-t", str(SLIDE_SECONDS)]
            args += ["-i", str(path)]
        # Zoom in 6% over the slide by rescaling each frame and cropping the
        # center (zoompan emits `d` frames per input frame: minutes long).
        filters = [
            f"[{i}:v]scale=w='trunc({WIDTH}*(1+0.06*t/{SLIDE_SECONDS})/2)*2':h=-2:eval=frame,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,format=yuv420p[s{i}]"
            for i in range(len(slides))
        ]
        last = "s0"
        for i in range(1, len(slides)):
            offset = i * (SLIDE_SECONDS - FADE_SECONDS)
            filters.append(
                f"[{last}][s{i}]xfade=transition=fade:duration={FADE_SECONDS}:offset={offset}[x{i}]"
            )
            last = f"x{i}"
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{last}]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-t",
            str(len(slides) * SLIDE_SECONDS),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
            "-movflags",
            "+faststart",
            str(out),
        ]
        subprocess.run(args, check=True)


def fetch_items(item_ids: list[str]) -> list[dict[str, Any]]:
    """The live items (every active listing when `item_ids` is empty). The
    DB session is closed before rendering: a long-idle Neon connection
    drops."""
    db = SessionLocal()
    try:
        item_ids = item_ids or [
            m.external_id
            for m in db.query(MarketplaceProduct).filter_by(status=ListingStatus.ACTIVE)
            if m.external_id
        ]
        with MercadoLibreAdapter(db) as ml:
            if not ml.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            items = []
            for item_id in item_ids:
                listing = ml.get_listing(item_id)
                if listing is None or listing.raw is None:
                    print(f"SKIP  {item_id}: no existe")
                    continue
                items.append(listing.raw)
            return items
    finally:
        db.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = fetch_items(sys.argv[1:])
    with httpx.Client(timeout=30) as http:
        for item in items:
            urls = [p.get("secure_url") or p.get("url") for p in item.get("pictures") or []]
            photos = []
            for url in [u for u in urls if u][:MAX_PHOTOS]:
                response = http.get(url)
                if response.status_code == 200:
                    photos.append(Image.open(BytesIO(response.content)))
            if not photos:
                print(f"SKIP  {item['id']}: sin fotos")
                continue
            out = OUT_DIR / f"{item['id']}.mp4"
            slides = slides_for(item, photos)
            render(slides, out)
            seconds = len(slides) * SLIDE_SECONDS - (len(slides) - 1) * FADE_SECONDS
            print(f"OK    {item['id']}: {out} ({seconds:.0f}s) {item['title'][:50]}")


if __name__ == "__main__":
    main()
