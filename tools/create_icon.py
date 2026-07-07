from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    source_path = ASSETS / "source_icon.png"
    if source_path.exists():
        base = Image.open(source_path).convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)
    else:
        base = draw_icon(1024)
    png_path = ASSETS / "app.png"
    ico_path = ASSETS / "app.ico"
    base.save(png_path)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [base.resize((size, size), Image.Resampling.LANCZOS) for size in sizes]
    images[-1].save(ico_path, sizes=[(size, size) for size in sizes], append_images=images[:-1])
    print(png_path)
    print(ico_path)


def draw_icon(size: int) -> Image.Image:
    scale = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    def box(values: tuple[int, int, int, int]) -> list[float]:
        return [value * scale for value in values]

    def pts(values: list[tuple[int, int]]) -> list[tuple[float, float]]:
        return [(x * scale, y * scale) for x, y in values]

    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle(box((64, 64, 960, 960)), radius=230 * scale, fill=(16, 91, 220, 255))
    td.rounded_rectangle(
        box((96, 96, 928, 928)),
        radius=205 * scale,
        outline=(77, 164, 255, 180),
        width=max(2, int(10 * scale)),
    )
    img.alpha_composite(tile)

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.polygon(
        pts(
            [
                (235, 542),
                (345, 352),
                (470, 288),
                (592, 300),
                (744, 412),
                (854, 430),
                (772, 516),
                (855, 604),
                (718, 606),
                (584, 724),
                (423, 704),
                (296, 622),
            ]
        ),
        fill=(255, 255, 255, 72),
    )
    sd.polygon(pts([(346, 352), (326, 218), (438, 309)]), fill=(255, 255, 255, 72))
    sd.polygon(pts([(608, 302), (702, 204), (707, 387)]), fill=(255, 255, 255, 72))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10 * scale))
    img.alpha_composite(shadow, (int(28 * scale), int(34 * scale)))

    d = ImageDraw.Draw(img)
    body = pts(
        [
            (202, 516),
            (318, 326),
            (454, 258),
            (596, 276),
            (738, 380),
            (878, 388),
            (792, 500),
            (890, 600),
            (716, 594),
            (594, 704),
            (418, 682),
            (282, 604),
        ]
    )
    d.polygon(body, fill=(111, 199, 255, 255))
    d.polygon(pts([(318, 326), (300, 174), (430, 278)]), fill=(130, 210, 255, 255))
    d.polygon(pts([(596, 276), (704, 158), (704, 360)]), fill=(130, 210, 255, 255))
    d.polygon(pts([(452, 262), (520, 120), (564, 284)]), fill=(36, 137, 235, 255))
    d.polygon(pts([(608, 704), (552, 842), (492, 695)]), fill=(47, 151, 239, 255))
    d.polygon(pts([(320, 570), (198, 630), (250, 518)]), fill=(39, 136, 230, 255))
    d.ellipse(box((646, 386, 694, 434)), fill=(8, 45, 116, 255))
    d.ellipse(box((662, 398, 677, 413)), fill=(255, 255, 255, 230))
    d.arc(box((600, 434, 752, 560)), start=15, end=116, fill=(6, 54, 132, 210), width=max(4, int(12 * scale)))
    for x in (448, 496, 544):
        d.line(pts([(x, 444), (x - 36, 510)]), fill=(13, 92, 184, 180), width=max(3, int(9 * scale)))
    d.arc(box((190, 250, 870, 754)), start=198, end=350, fill=(227, 248, 255, 110), width=max(4, int(14 * scale)))
    return img


if __name__ == "__main__":
    main()
