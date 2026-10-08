"""XobaMetrics logo: four chart bars spelling XOBA, "metrics" beneath. Text is
converted to outlines so the SVGs need no font installed.

    python3 brand/logo.py brand            # the SVGs in brand/
    python3 brand/emit_js.py frontend      # src/components/Logo.js and public/favicon.svg
"""
import os
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = {w: TTFont(os.path.join(HERE, "fonts", f"outfit-{w}.ttf")) for w in (600, 800)}
# Heights follow the sketch: X short, O tallest, B tall, A medium.
BARS = [("X", 150, "#06B6D4"), ("O", 280, "#2563EB"), ("B", 240, "#7C3AED"), ("A", 195, "#DB2777")]
W, GAP, X0, BASE, R, DOT_GAP, DOT_R = 100, 24, 64, 360, 22, 30, 13
GROUP_W = 4 * W + 3 * GAP

def glyph(font, ch):
    gs = font.getGlyphSet()
    name = font.getBestCmap()[ord(ch)]
    return gs, name, gs[name].width

def text_path(text, weight, size, x, baseline, tracking=0.0):
    """Outline path for `text` starting at x; returns (d, width)."""
    font = FONTS[weight]
    scale = size / font["head"].unitsPerEm
    d, cursor = [], 0.0
    for i, ch in enumerate(text):
        gs, name, adv = glyph(font, ch)
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + cursor, baseline)))
        d.append(pen.getCommands())
        cursor += adv * scale + (tracking * size if i < len(text) - 1 else 0)
    return " ".join(d), cursor

def ink_bounds(ch, weight):
    font = FONTS[weight]
    gs, name, _ = glyph(font, ch)
    pen = BoundsPen(gs); gs[name].draw(pen)
    return pen.bounds, font["head"].unitsPerEm

def bars():
    out = []
    for i, (letter, h, color) in enumerate(BARS):
        x, top = X0 + i * (W + GAP), BASE - h
        size = 78
        (xmin, _, xmax, _), upm = ink_bounds(letter, 800)
        s = size / upm
        lx = x + W / 2 - (xmin + xmax) / 2 * s   # centre the ink, not the advance
        d, _ = text_path(letter, 800, size, lx, BASE - 24)
        out.append(
            f'<path d="M{x} {BASE}V{top+R}a{R} {R} 0 0 1 {R} -{R}h{W-2*R}a{R} {R} 0 0 1 {R} {R}V{BASE}Z" fill="{color}"/>'
            f'<circle cx="{x+W/2}" cy="{top-DOT_GAP}" r="{DOT_R}" fill="{color}"/>'
            f'<path d="{d}" fill="#fff"/>')
    return "".join(out)

def wordmark(ink, baseline=470):
    tracking = 0.04
    _, natural = text_path("metrics", 600, 100, 0, 0, tracking)
    size = 100 * GROUP_W / natural          # same width as the bars
    d, width = text_path("metrics", 600, size, X0, baseline, tracking)
    return f'<path d="{d}" fill="{ink}"/>'

def svg(body, w, h, bg=None):
    back = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{back}{body}</svg>'

def icon_body():
    top = BASE - max(h for _, h, _ in BARS) - DOT_GAP - DOT_R
    s = 420 / GROUP_W
    tx, ty = (600 - GROUP_W * s) / 2 - X0 * s, (600 - (BASE - top) * s) / 2 - top * s
    return f'<g transform="translate({tx:.2f} {ty:.2f}) scale({s:.4f})">{bars()}</g>'

files = {
    "xobametrics-logo": svg(bars() + wordmark("#0F172A"), 600, 520),
    "xobametrics-logo-white": svg(bars() + wordmark("#FFFFFF"), 600, 520),
    "xobametrics-icon": svg(icon_body(), 600, 600, "#FFFFFF"),
    "xobametrics-icon-dark": svg(icon_body(), 600, 600, "#0B1120"),
}
import sys
if __name__ == "__main__":
    for name, content in files.items():
        open(f"{sys.argv[1]}/{name}.svg", "w").write(content)
