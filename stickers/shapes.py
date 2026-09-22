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


def _densify(pts, step):
    """Insert points so no two neighbours are more than `step` apart."""
    out = []
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        out.append((x0, y0))
        dx, dy = x1 - x0, y1 - y0
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > step:
            for k in range(1, int(dist / step) + 1):
                t = k * step / dist
                if t < 1.0:
                    out.append((x0 + dx * t, y0 + dy * t))
    return out


def mask(pts, size, inset=0, supersample=4):
    """
    Fill `pts` into an L mask of `size`, eaten in by `inset` output pixels.

    The inset is a TRUE uniform inset — a morphological erosion by a disk,
    stamped as overlapping circles along a densified outline. Two earlier
    approaches were wrong and both are worth remembering:

    - Scaling the polygon toward its centroid shortens a starburst's spikes
      instead of thinning them, so the points ended up with no border at all.
    - Stroking the outline with `ImageDraw.line(width=2*inset, joint='curve')`
      is geometrically right but Pillow's wide-line renderer leaves unfilled
      slivers at big widths, which showed up as hairline whiskers radiating
      across the white border.

    Stamping circles has no such failure mode: every pixel within `inset` of
    the boundary is covered, by construction.
    """
    big = int(size * supersample)
    k = big / VIEWBOX
    scaled = [(x * k, y * k) for x, y in pts]

    img = Image.new('L', (big, big), 0)
    draw = ImageDraw.Draw(img)
    draw.polygon(scaled, fill=255)

    if inset > 0:
        radius = inset * supersample
        # Step as a fraction of the radius. The union of discs scallops
        # between centres with amplitude ~ radius * (1 - cos(asin(step/2r))),
        # so 0.5 leaves a ripple you can see on the cut edge at 1024px and
        # 0.2 puts it well under a pixel. The extra discs are cheap.
        for x, y in _densify(scaled, radius * 0.2):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                         fill=0)
    return img.resize((size, size), Image.LANCZOS)
