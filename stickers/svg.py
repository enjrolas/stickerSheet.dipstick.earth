"""
A sticker as a single SVG file.

The raster pipeline (imaging.make_diecut) and this module must agree, or a
downloaded SVG would not match the PNG next to it. They use the same trick for
the border: clip everything to the outline, then STROKE that same outline from
inside the clip. Half the stroke falls outside and is clipped away, so exactly
`width / 2` is left lying inside the edge — a true uniform inset, on a spiky
starburst as much as on a blob. Scaling the path toward its centroid instead
(the obvious approach) shortens the spikes rather than thinning them and
leaves the points with no border at all.

Vector all the way out to the artwork; the photograph itself is necessarily a
raster `<image>`, either linked or inlined as a data URI.
"""

import base64
import mimetypes
import os

from django.conf import settings
from django.utils.html import escape

from . import shapes

VIEWBOX = 512
INK = '#141210'
VINYL = '#ffffff'
KEYLINE_RATIO = 0.006


def _data_uri(path):
    """Inline a file as base64, so the SVG stands alone."""
    mime, _ = mimetypes.guess_type(path)
    with open(path, 'rb') as fh:
        blob = base64.b64encode(fh.read()).decode('ascii')
    return 'data:%s;base64,%s' % (mime or 'image/jpeg', blob)


def sticker_svg(sticker, href=None, embed=False, title=None):
    """
    Compose the die-cut sticker as SVG source.

    `href`  absolute URL to the artwork when not embedding.
    `embed` inline the artwork as a data URI instead, making the file portable.
    """
    slug = sticker.resolved_shape
    d = shapes.raw_path(slug) if slug else None
    if not d:
        return None

    border = VIEWBOX * settings.STICKER_BORDER_RATIO
    keyline = VIEWBOX * KEYLINE_RATIO

    if embed:
        # A video has no still of its own; its poster is the frame we cut.
        source = sticker._derivative_path('.poster.jpg') if sticker.is_video \
            else (sticker.media.path if sticker.media else None)
        if not source or not os.path.exists(source):
            source = sticker._derivative_path('.thumb.jpg')
        if not source or not os.path.exists(source):
            return None
        art = _data_uri(source)
    else:
        art = href or ''

    label = escape(title or str(sticker.species))
    clip_id = 'cut-%s' % (sticker.slug or sticker.pk)

    return '''<svg xmlns="http://www.w3.org/2000/svg" \
xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {vb} {vb}" \
width="{vb}" height="{vb}" role="img" aria-labelledby="t-{cid}">
  <title id="t-{cid}">{label}</title>
  <defs>
    <clipPath id="{cid}"><path d="{d}"/></clipPath>
  </defs>
  <g clip-path="url(#{cid})">
    <path d="{d}" fill="{vinyl}"/>
    <image xlink:href="{art}" href="{art}" x="0" y="0" width="{vb}" height="{vb}"
           preserveAspectRatio="xMidYMid slice"/>
    <!-- Stroked from inside the clip: the outer half is cut away, leaving a
         uniform band of exactly half the stroke width inside the edge. -->
    <path d="{d}" fill="none" stroke="{vinyl}" stroke-width="{bw}" \
stroke-linejoin="round"/>
    <path d="{d}" fill="none" stroke="{ink}" stroke-width="{kw}" \
stroke-linejoin="round"/>
  </g>
</svg>
'''.format(vb=VIEWBOX, cid=escape(str(clip_id)), label=label, d=d,
           vinyl=VINYL, ink=INK, art=escape(art),
           bw=round(border * 2, 2), kw=round(keyline * 2, 2))
