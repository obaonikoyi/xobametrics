"""Write frontend/src/components/Logo.js and public favicons from logo.py's shapes."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logo as L

def r(d):  # one decimal is plenty at these sizes
    return re.sub(r"-?\d+\.\d+", lambda m: f"{float(m.group()):.1f}".rstrip("0").rstrip("."), d)

bars, letters, dots = [], [], []
for i, (letter, h, color) in enumerate(L.BARS):
    x, top = L.X0 + i * (L.W + L.GAP), L.BASE - h
    R = L.R
    bars.append((f"M{x} {L.BASE}V{top+R}a{R} {R} 0 0 1 {R} -{R}h{L.W-2*R}a{R} {R} 0 0 1 {R} {R}V{L.BASE}Z", color))
    dots.append((x + L.W / 2, top - L.DOT_GAP, color))
    (xmin, _, xmax, _), upm = L.ink_bounds(letter, 800)
    s = 78 / upm
    d, _ = L.text_path(letter, 800, 78, x + L.W / 2 - (xmin + xmax) / 2 * s, L.BASE - 24)
    letters.append(r(d))
tracking = 0.04
_, natural = L.text_path("metrics", 600, 100, 0, 0, tracking)
word, _ = L.text_path("metrics", 600, 100 * L.GROUP_W / natural, L.X0, 470, tracking)

top = L.BASE - max(h for _, h, _ in L.BARS) - L.DOT_GAP - L.DOT_R   # 37
pad = 4
mark_box = f"{L.X0 - pad} {top - pad} {L.GROUP_W + 2*pad} {L.BASE - top + 2*pad}"

js = f'''// Generated from brand/ (XOBA chart bars over "metrics"); edit the brand
// source and regenerate rather than hand-editing these paths.
const BARS = {[{"d": d, "color": c} for d, c in bars]};
const DOTS = {[{"cx": cx, "cy": cy, "color": c} for cx, cy, c in dots]};
const LETTERS = {letters};
const WORDMARK = "{r(word)}";

function Bars({{ letters = true }}) {{
  return (
    <>
      {{BARS.map((b) => <path key={{b.d}} d={{b.d}} fill={{b.color}} />)}}
      {{DOTS.map((d) => <circle key={{d.cx}} cx={{d.cx}} cy={{d.cy}} r={{{L.DOT_R}}} fill={{d.color}} />)}}
      {{letters && LETTERS.map((d) => <path key={{d}} d={{d}} fill="#fff" />)}}
    </>
  );
}}

/** The full logo. "metrics" takes the text colour, so it follows light and dark mode. */
export default function Logo({{ className = "h-12 w-auto", title = "XobaMetrics" }}) {{
  return (
    <svg viewBox="{L.X0 - 4} {top - pad} {L.GROUP_W + 8} {474 - (top - pad)}" className={{className}} role="img" aria-label={{title}}>
      <Bars />
      <path d={{WORDMARK}} fill="currentColor" />
    </svg>
  );
}}

/** The bars on their own, for small spaces and loading states. */
export function LogoMark({{ className = "h-8 w-auto", title = "XobaMetrics", letters = true }}) {{
  return (
    <svg viewBox="{mark_box}" className={{className}} role="img" aria-label={{title}}>
      <Bars letters={{letters}} />
    </svg>
  );
}}
'''
js = js.replace("'", '"')
open(sys.argv[1] + "/src/components/Logo.js", "w").write(js)

# Favicon: bars and dots only; letters are unreadable at 16px.
fav = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{mark_box}">'
       + "".join(f'<path d="{d}" fill="{c}"/>' for d, c in bars)
       + "".join(f'<circle cx="{cx}" cy="{cy}" r="{L.DOT_R}" fill="{c}"/>' for cx, cy, c in dots) + "</svg>")
open(sys.argv[1] + "/public/favicon.svg", "w").write(fav)
