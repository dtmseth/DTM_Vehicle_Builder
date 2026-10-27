"""Build the rotating Windows startup splashes from owner-supplied photos."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = Path(__file__).resolve().parent
SOURCE_DIR = ICON_DIR / "splash_sources"
SOURCE_LOGO = (
    ROOT / "src" / "dtm_buildsheet" / "resources" / "assets" / "dtm_form_logo.webp"
)
SOURCES = (
    SOURCE_DIR / "vehicle-1.jpg",
    SOURCE_DIR / "vehicle-2.jpg",
    SOURCE_DIR / "equipment-3.jpg",
    SOURCE_DIR / "vehicle-4.jpg",
    SOURCE_DIR / "vehicle-5.jpg",
    SOURCE_DIR / "vehicle-6.jpg",
)

WIDTH, HEIGHT = 960, 540
PHOTO_LEFT = 240


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _photo_background(source: Image.Image) -> Image.Image:
    """Fade one untouched photo into a clean logo-safe charcoal field."""
    background = Image.new("RGBA", (WIDTH, HEIGHT))
    background_pixels = background.load()
    for y in range(HEIGHT):
        vertical = y / max(HEIGHT - 1, 1)
        for x in range(WIDTH):
            horizontal = x / max(WIDTH - 1, 1)
            shade = round(26 - (10 * vertical) - (4 * horizontal))
            background_pixels[x, y] = (shade, shade + 2, shade + 4, 255)

    sharp = ImageOps.fit(
        source,
        (WIDTH - PHOTO_LEFT, HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).convert("RGBA")
    sharp_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    sharp_layer.alpha_composite(sharp, (PHOTO_LEFT, 0))

    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    mask_pixels = mask.load()
    fade_start, fade_end = PHOTO_LEFT, 445
    for x in range(WIDTH):
        if x <= fade_start:
            alpha = 0
        elif x >= fade_end:
            alpha = 255
        else:
            alpha = round(255 * (x - fade_start) / (fade_end - fade_start))
        for y in range(HEIGHT):
            mask_pixels[x, y] = alpha
    return Image.composite(sharp_layer, background, mask)


def _add_legibility_gradients(image: Image.Image) -> None:
    left = Image.new("RGBA", image.size, (0, 0, 0, 0))
    left_pixels = left.load()
    for x in range(WIDTH):
        amount = max(0.0, 1.0 - (x / 610.0))
        alpha = round(226 * amount**1.55)
        for y in range(HEIGHT):
            left_pixels[x, y] = (10, 13, 16, alpha)
    image.alpha_composite(left)

    bottom = Image.new("RGBA", image.size, (0, 0, 0, 0))
    bottom_pixels = bottom.load()
    for y in range(HEIGHT):
        amount = max(0.0, (y - 395) / 145.0)
        alpha = round(125 * amount**1.35)
        for x in range(WIDTH):
            bottom_pixels[x, y] = (6, 8, 11, alpha)
    image.alpha_composite(bottom)


def _add_branding(image: Image.Image) -> None:
    logo = Image.open(SOURCE_LOGO).convert("RGBA")
    logo.thumbnail((350, 145), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, (44, 48))

    draw = ImageDraw.Draw(image)
    title = "VEHICLE BUILDER"
    title_font = _font(30, bold=True)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    draw.text(
        (44 + (350 - title_width) // 2, 198),
        title,
        font=title_font,
        fill=(248, 249, 251, 255),
        stroke_width=1,
        stroke_fill=(9, 11, 14, 210),
    )
    draw.rounded_rectangle((44, 244, 394, 248), radius=2, fill=(210, 174, 76, 255))


def build() -> None:
    for index, source_path in enumerate(SOURCES, start=1):
        source = Image.open(source_path).convert("RGB")
        splash = _photo_background(source)
        _add_legibility_gradients(splash)
        _add_branding(splash)
        splash.convert("RGB").save(
            ICON_DIR / f"splash-{index}.jpg",
            "JPEG",
            quality=91,
            optimize=True,
            progressive=True,
        )


if __name__ == "__main__":
    build()
