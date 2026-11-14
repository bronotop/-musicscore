"""Generate ``assets/music2score.ico`` used by the one-click launcher.

Run with the project venv (needs Pillow):

    ./.venv/Scripts/python.exe scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "music2score.ico"
PREVIEW = ROOT / "assets" / "music2score-preview.png"


def gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    strip = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        strip.putpixel(
            (0, y),
            tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)),
        )
    return strip.resize((size, size), Image.Resampling.BILINEAR)


def note_head(center: tuple[int, int], width: int, height: int, angle: float) -> Image.Image:
    layer = Image.new("RGBA", (width * 2, height * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    box = (
        width // 2,
        height // 2,
        width // 2 + width,
        height // 2 + height,
    )
    draw.ellipse(box, fill=(255, 255, 255, 255))
    layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return layer


def build() -> Image.Image:
    canvas = gradient(SIZE, (15, 23, 42), (30, 64, 175)).convert("RGBA")

    # Soft staff lines behind the note.
    staff = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    staff_draw = ImageDraw.Draw(staff)
    for index in range(5):
        y = 380 + index * 96
        staff_draw.line([(120, y), (904, y)], fill=(255, 255, 255, 46), width=9)
    canvas = Image.alpha_composite(canvas, staff)

    note = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(note)

    # Stems.
    draw.rectangle([446, 300, 480, 706], fill=(255, 255, 255, 255))
    draw.rectangle([740, 196, 774, 604], fill=(255, 255, 255, 255))

    # Beam.
    draw.polygon(
        [(446, 300), (774, 196), (774, 286), (446, 390)],
        fill=(255, 255, 255, 255),
    )

    # Note heads, slightly rotated like a handwritten score.
    head_a = note_head((0, 0), 196, 136, -22)
    note.alpha_composite(head_a, (352 - head_a.width // 2, 706 - head_a.height // 2))
    head_b = note_head((0, 0), 196, 136, -22)
    note.alpha_composite(head_b, (646 - head_b.width // 2, 604 - head_b.height // 2))

    # Glow under the note for a little depth.
    glow = note.filter(ImageFilter.GaussianBlur(34))
    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, note)

    # Rounded icon shape.
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=228, fill=255
    )
    canvas.putalpha(mask)
    return canvas


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon = build()
    icon.save(PREVIEW, "PNG")
    icon.save(
        OUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"preview {PREVIEW}")


if __name__ == "__main__":
    main()
