"""Draw the Concert Wrapped card as a shareable PNG (1080 px wide). Pillow + numpy, no Streamlit."""
import io
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
WIDTH, MIN_HEIGHT, PAD = 1080, 1350, 84
STOPS = [(0.0, (29, 185, 84)), (0.55, (15, 107, 143)), (1.0, (91, 42, 134))]  # green → teal → purple


def _font(weight: str, size: int):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, f"Inter-{weight}.otf"), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _gradient(w: int, h: int) -> Image.Image:
    y, x = np.mgrid[0:h, 0:w]
    t = (x / max(w - 1, 1)) * 0.45 + (y / max(h - 1, 1)) * 0.55
    out = np.zeros((h, w, 3), dtype=np.float64)
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        m = (t >= t0) & (t <= t1)
        f = ((t - t0) / (t1 - t0))[m][:, None]
        out[m] = np.array(c0) * (1 - f) + np.array(c1) * f
    return Image.fromarray(out.astype(np.uint8), "RGB")


def _wrap(draw, text: str, font, max_w: int) -> list:
    words, lines, cur = str(text).split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def render_wrapped_png(w: dict, username: str, highlights: list) -> bytes:
    """w: wrapped_summary() output. highlights: [(label, value), ...] in display order."""
    layer = Image.new("RGBA", (WIDTH, 3000), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white, soft = (255, 255, 255, 255), (255, 255, 255, 205)
    inner = WIDTH - 2 * PAD
    y = PAD

    d.text((PAD, y), f"SETLISTR · {username.upper()}", font=_font("Medium", 30), fill=soft)
    y += 58
    for line in _wrap(d, f"{w['label']} Concert Wrapped", _font("ExtraBold", 78), inner):
        d.text((PAD, y), line, font=_font("ExtraBold", 78), fill=white)
        y += 92
    y += 34

    stats = [(f"{w['concerts']:,}", "CONCERTS"), (f"{w['artists']:,}", "ARTISTS"),
             (f"{w['songs']:,}", "SONGS HEARD"), (f"{w['hours']}", "HOURS OF MUSIC")]
    col_w = inner // 2
    for i, (num, label) in enumerate(stats):
        cx, cy = PAD + (i % 2) * col_w, y + (i // 2) * 205
        d.text((cx, cy), num, font=_font("ExtraBold", 112), fill=white)
        d.text((cx + 4, cy + 146), label, font=_font("Medium", 28), fill=soft)
    y += 2 * 205 + 30

    d.line([(PAD, y), (WIDTH - PAD, y)], fill=(255, 255, 255, 90), width=2)
    y += 40
    for label, value in highlights:
        d.text((PAD, y), label.upper(), font=_font("Medium", 26), fill=soft)
        y += 40
        for line in _wrap(d, value, _font("Bold", 42), inner):
            d.text((PAD, y), line, font=_font("Bold", 42), fill=white)
            y += 54
        y += 26

    height = max(MIN_HEIGHT, y + PAD)
    footer = "setlistr.streamlit.app"
    ff = _font("Medium", 26)
    d.text((WIDTH - PAD - d.textlength(footer, font=ff), height - PAD + 10), footer, font=ff, fill=soft)

    img = _gradient(WIDTH, height).convert("RGBA")
    img.alpha_composite(layer.crop((0, 0, WIDTH, height)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
