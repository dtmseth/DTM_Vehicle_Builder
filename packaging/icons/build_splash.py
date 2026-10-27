"""Regenerate the Windows startup splash from the existing DTM brand asset."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SOURCE_LOGO = ROOT / "src" / "dtm_buildsheet" / "resources" / "assets" / "dtm_form_logo.webp"
OUTPUT = Path(__file__).with_name("splash.png")


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


def build() -> None:
    width, height = 560, 300
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    top = (22, 29, 77)
    bottom = (30, 39, 97)
    for y in range(height):
        amount = y / max(height - 1, 1)
        color = tuple(round(a + (b - a) * amount) for a, b in zip(top, bottom))
        for x in range(width):
            pixels[x, y] = (*color, 255)

    logo = Image.open(SOURCE_LOGO).convert("RGBA")
    logo.thumbnail((410, 160), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, ((width - logo.width) // 2, 28))

    draw = ImageDraw.Draw(image)
    title = "VEHICLE BUILDER"
    title_font = _font(25, bold=True)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    draw.text(
        ((width - title_width) // 2, 194),
        title,
        font=title_font,
        fill=(255, 255, 255, 255),
        stroke_width=1,
        stroke_fill=(12, 17, 48, 255),
    )
    draw.rounded_rectangle((30, 239, width - 30, 242), radius=2, fill=(200, 169, 81, 255))
    image.convert("RGB").save(OUTPUT, "PNG", optimize=True)


if __name__ == "__main__":
    build()
