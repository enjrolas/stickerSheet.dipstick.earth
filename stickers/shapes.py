"""
The die-cut silhouettes in `stickers/shapes/`.

Those files are hand-drawn SVGs on a 512x512 viewBox, each holding one closed
path with `id="sticker-shape"`. They only ever use M / L / C / Z, so rather
than pull in a full SVG rasteriser (cairosvg wants libcairo, ImageMagick's SVG
delegate is unreliable) we parse those four commands, flatten the cubics to a
polygon and let Pillow fill it. ~60 lines, no new dependency.

If a future shape uses arcs (A) or quadratics (Q), this parser will skip the
command and the outline will be wrong — add the case rather than guessing.
"""

import os
import re

from PIL import Image, ImageDraw

SHAPE_DIR = os.path.join(os.path.dirname(__file__), 'shapes')
VIEWBOX = 512.0
CUBIC_STEPS = 24  # flattening resolution; 24 is smooth at 1024px output

_TOKEN = re.compile(r'[MmLlCcZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?')
_PATH = re.compile(r'id="sticker-shape"[^>]*?\sd="([^"]*)"')
_ANY_PATH = re.compile(r'\sd="(M[^"]*)"')


def available():
    """[(slug, 'Human label'), ...] for the shapes on disk, in file order."""
    out = []
    for fname in sorted(os.listdir(SHAPE_DIR)):
        if not fname.endswith('.svg'):
            continue
        slug = os.path.splitext(fname)[0]
        label = slug.split('-', 1)[1].replace('-', ' ').capitalize()
        out.append((slug, label))
    return out


def _cubic(p0, p1, p2, p3, steps=CUBIC_STEPS):
    """Flatten one cubic Bezier to a list of points (excluding p0)."""
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = (u * u * u * p0[0] + 3 * u * u * t * p1[0]
             + 3 * u * t * t * p2[0] + t * t * t * p3[0])
        y = (u * u * u * p0[1] + 3 * u * u * t * p1[1]
             + 3 * u * t * t * p2[1] + t * t * t * p3[1])
        pts.append((x, y))
    return pts


def parse_path(d):
    """SVG path data -> list of (x, y) in viewBox space. Handles M/L/C/Z."""
    tokens = _TOKEN.findall(d)
    pts, i = [], 0
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    cmd = None
    while i < len(tokens):
        tok = tokens[i]
        if tok in 'MmLlCcZz':
            cmd = tok
            i += 1
            if cmd in 'Zz':
                if start and (not pts or pts[-1] != start):
                    pts.append(start)
                continue
        # An omitted command repeats the previous one (SVG shorthand).
        rel = cmd.islower()
        if cmd in 'Mm':
            x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = start = (x, y)
            pts.append(cur)
            cmd = 'l' if rel else 'L'   # subsequent pairs are implicit lineto
        elif cmd in 'Ll':
            x, y = float(tokens[i]), float(tokens[i + 1]); i += 2
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y)
            pts.append(cur)
        elif cmd in 'Cc':
            vals = [float(v) for v in tokens[i:i + 6]]; i += 6
            if rel:
                p1 = (cur[0] + vals[0], cur[1] + vals[1])
                p2 = (cur[0] + vals[2], cur[1] + vals[3])
                p3 = (cur[0] + vals[4], cur[1] + vals[5])
            else:
                p1, p2, p3 = (vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])
            pts.extend(_cubic(cur, p1, p2, p3))
            cur = p3
        else:
            i += 1  # unsupported command; skip the token
    return pts


def raw_path(slug):
    """The shape's `d` attribute verbatim, for composing an SVG sticker."""
    path = os.path.join(SHAPE_DIR, '%s.svg' % slug)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        svg = fh.read()
    match = _PATH.search(svg) or _ANY_PATH.search(svg)
    return match.group(1) if match else None


def load(slug):
    """Read a shape file and return its polygon, or None if it isn't there."""
    path = os.path.join(SHAPE_DIR, '%s.svg' % slug)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        svg = fh.read()
    match = _PATH.search(svg) or _ANY_PATH.search(svg)
    if not match:
        return None
    pts = parse_path(match.group(1))
    return pts if len(pts) >= 3 else None


def mask(pts, size, inset=0, supersample=4):
    """
    Fill `pts` into an L mask of `size`, eaten in by `inset` output pixels.

    The inset is a TRUE uniform inset, not a scale toward the centroid: the
    filled polygon is re-stroked in black at twice the inset width, which eats
    exactly `inset` pixels inward all the way round. Centroid scaling was tried
    first and is wrong on a spiky outline — it shortens the spikes instead of
    thinning them, so a starburst lost its white border at the points while
    keeping a fat one in the middle.
    """
    big = int(size * supersample)
    k = big / VIEWBOX
    scaled = [(x * k, y * k) for x, y in pts]

    img = Image.new('L', (big, big), 0)
    draw = ImageDraw.Draw(img)
    draw.polygon(scaled, fill=255)
    if inset > 0:
        width = max(1, int(round(inset * supersample * 2)))
        # Stroke a DECIMATED copy. Flattening the cubics leaves consecutive
        # points a fraction of a pixel apart at this scale, and Pillow's
        # wide-line renderer degenerates on a near-zero-length segment — the
        # quad it builds for the segment flips and throws a black spur out
        # across the border. Dropping points closer than ~2px removes them.
        draw.line(_decimate(scaled, 2.0), fill=0, width=width, joint='curve')
    return img.resize((size, size), Image.LANCZOS)


def _decimate(pts, min_dist):
    """Closed polyline with points nearer than `min_dist` dropped."""
    out = [pts[0]]
    for x, y in pts[1:]:
        px, py = out[-1]
        if (x - px) ** 2 + (y - py) ** 2 >= min_dist * min_dist:
            out.append((x, y))
    if len(out) < 3:
        out = list(pts)
    return out + [out[0]]
