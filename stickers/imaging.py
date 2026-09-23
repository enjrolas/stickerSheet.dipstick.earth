"""
Turning a dipstick capture into a die-cut sticker.

Every function here is best-effort and writes a file next to the original.
Callers swallow exceptions — a bad upload must never 500 the submit form.

The die-cut look: square crop, squircle mask, thick white vinyl border, thin
ink keyline, transparent everywhere else. That matches the hand-drawn
`basic dipstick sticker.png` already used across dipstick.earth.
"""

import os
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from . import shapes

# Derivatives are written by whichever user is running: apache (www-data) for
# a public submission, `japhy` for a shell rebuild. Pillow and ffmpeg both go
# through the process umask and land 0644, which means the OTHER user can then
# never overwrite them — and build_derivatives() swallows the failure, so it
# fails silently. Group-writable keeps both able to rebuild.
DERIVATIVE_MODE = 0o664

# Zoom 1.0 is "the largest square that fits" — the classic cover crop. Below
# 1.0 the square grows past the short side and the picture is padded, letting
# you pull back to the whole frame; above it you push in. The useful floor is
# per-image (min(w,h)/max(w,h) shows everything), so this is just a hard stop.
MIN_ZOOM = 0.2
MAX_ZOOM = 4.0

# Padding shown around a zoomed-out picture. White, so on a die-cut sticker it
# reads as the photo floating on the vinyl rather than as a grey box.
PAD = (255, 255, 255)

# Ink keyline width as a fraction of the sticker. Shared with
# build_shape_masks so the preview art and the cut art agree exactly.
KEYLINE_RATIO = 0.006

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.mkv', '.3gp'}

# The mask is drawn this many times oversized and then downsampled, which is
# what keeps the die-cut edge smooth instead of stair-stepped.
SUPERSAMPLE = 4

INK = (20, 18, 16, 255)      # --ink from style-sticker.css
VINYL = (255, 255, 255, 255)


def _finalize(path):
    """chmod a freshly written derivative so either user can replace it."""
    try:
        os.chmod(path, DERIVATIVE_MODE)
    except OSError:
        pass  # not ours to chmod; the file is still readable
    return path


def is_video(filename):
    return os.path.splitext(filename or '')[1].lower() in VIDEO_EXTENSIONS


def _open_upright(path):
    """Open an image with EXIF rotation already applied."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert('RGB')


def focal_crop(img, framing=None):
    """
    Take a square out of `img` according to (focal_x, focal_y, zoom).

    zoom 1.0 is the largest square that fits (a cover crop). Above 1.0 moves
    in closer. **Below 1.0 the square grows past the short side**, so the
    picture no longer fills it and the remainder is padded — that is what
    "zoom out" means here, and it is the only way to keep the edges of a
    landscape shot instead of having them cropped away.

    Zooming out stops once the whole image is visible: `side` is capped at
    max(w, h), so you cannot pull back into an endless white field.

    While the square still fits inside the image it is clamped to stay there,
    so dragging to an edge stops. Once it is larger than a dimension there is
    nothing to clamp against and it centres on that axis instead.

    **This is duplicated in the browser** (stickers/static/stickers/js/framer.js)
    so the live preview matches what gets cut. Change one, change the other.
    """
    w, h = img.size
    if not framing:
        focal_x, focal_y, zoom = 0.5, 0.5, 1.0
    else:
        focal_x, focal_y, zoom = framing
    zoom = max(MIN_ZOOM, min(float(zoom or 1.0), MAX_ZOOM))

    side = min(w, h) / zoom
    side = min(side, float(max(w, h)))      # no further out than the whole image

    def place(focal, extent):
        start = focal * extent - side / 2.0
        if side <= extent:
            return max(0.0, min(start, extent - side))
        return (extent - side) / 2.0        # wider than the image: centre it

    left, top = place(focal_x, w), place(focal_y, h)

    # Round the SIDE once and derive both edges from it. Rounding each edge
    # independently can leave the box a pixel taller than it is wide, which
    # then gets squashed into a square on resize.
    side_px = max(1, int(round(side)))
    left_px, top_px = int(round(left)), int(round(top))

    # Composite rather than crop: Image.crop() pads with black outside the
    # bounds, and a zoomed-out sticker wants the vinyl colour behind it.
    out = Image.new('RGB', (side_px, side_px), PAD)
    out.paste(img, (-left_px, -top_px))
    return out


def _square_crop(img):
    """Backwards-compatible centre crop."""
    return focal_crop(img, None)


def _squircle_mask(size, radius_ratio=0.22):
    """An L-mask: rounded square, drawn oversized and downsampled."""
    big = size * SUPERSAMPLE
    mask = Image.new('L', (big, big), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, big - 1, big - 1),
                           radius=int(big * radius_ratio), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def make_diecut(source_path, out_path, size, border_ratio, shape=None,
                framing=None):
    """
    Write a transparent PNG sticker: photo, white vinyl border, ink keyline.

    `shape` is a slug from stickers/shapes/ (e.g. '06-splat'). Without one, or
    if the file is missing, it falls back to the plain rounded square so a
    sticker is always produced.
    """
    if not out_path:
        return None

    keyline = max(1, int(size * KEYLINE_RATIO))

    # The photo fills the whole canvas and the silhouette masks it, rather than
    # being inset into a box — that is what lets an irregular outline (a splat,
    # a starburst) crop the image to its own edge.
    photo = focal_crop(_open_upright(source_path), framing).resize(
        (size, size), Image.LANCZOS).convert('RGBA')

    points = shapes.load(shape) if shape else None
    if points:
        border = max(2, int(size * border_ratio))
        outer = shapes.mask(points, size)
        photo_mask = shapes.mask(points, size, inset=border)
        key_inner = shapes.mask(points, size, inset=keyline)
    else:
        outer = _squircle_mask(size)
        inset = size - 2 * int(size * border_ratio)
        photo_mask = Image.new('L', (size, size), 0)
        photo_mask.paste(_squircle_mask(inset, radius_ratio=0.20),
                         (int(size * border_ratio), int(size * border_ratio)))
        key_inner = Image.new('L', (size, size), 0)
        key_inner.paste(_squircle_mask(size - 2 * keyline), (keyline, keyline))

    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    # vinyl
    canvas.paste(Image.new('RGBA', (size, size), VINYL), (0, 0), outer)
    # ink keyline, as the difference between the outline and an inset of it
    ring = ImageChops.subtract(outer, key_inner)
    canvas.paste(Image.new('RGBA', (size, size), INK), (0, 0), ring)
    # the photograph
    canvas.paste(photo, (0, 0), photo_mask)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas.save(out_path, 'PNG', optimize=True)
    return _finalize(out_path)


def make_thumb(source_path, out_path, width, framing=None):
    """Grid thumbnail — square, JPEG, progressive."""
    if not out_path:
        return None
    img = focal_crop(_open_upright(source_path), framing).resize(
        (width, width), Image.LANCZOS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, 'JPEG', quality=85, optimize=True, progressive=True)
    return _finalize(out_path)


def make_lowres(source_path, out_path, width, framing=None):
    """Tiny blurred LQIP placeholder, inlined-cheap at a couple of KB."""
    if not out_path:
        return None
    img = focal_crop(_open_upright(source_path), framing).resize(
        (width, width), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, 'JPEG', quality=60, optimize=True)
    return _finalize(out_path)


def compress_video(source_path, out_path, max_width=900):
    """
    Re-encode a clip small enough to put on a web page.

    Phone footage arrives enormous — one 12 MB clip was being served whole to
    every visitor who scrolled past it. This scales the long edge down, drops
    the audio (every sticker is muted anyway) and moves the moov atom to the
    front so playback can start before the file has finished arriving.

    CRF 28 at this size is visually fine for something rendered a few hundred
    pixels wide inside a die-cut. Returns None if ffmpeg fails, and callers
    fall back to the original rather than showing nothing.
    """
    if not out_path:
        return None
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error', '-i', source_path,
        '-vf', "scale='min(%d,iw)':-2" % max_width,
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '28',
        '-pix_fmt', 'yuv420p',
        '-an',                          # muted everywhere it is used
        '-movflags', '+faststart',      # start playing before it all lands
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return None
    # A "compressed" file bigger than the original helps nobody.
    try:
        if os.path.getsize(out_path) >= os.path.getsize(source_path):
            os.remove(out_path)
            return None
    except OSError:
        pass
    return _finalize(out_path)


def video_poster(source_path, out_path, at_seconds=1):
    """
    Pull a frame out of a video with ffmpeg so the rest of the pipeline has an
    image to work from. Returns the poster path, or None if ffmpeg failed.
    """
    if not out_path:
        return None
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-ss', str(at_seconds), '-i', source_path,
        '-frames:v', '1', '-q:v', '3', out_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # Clip shorter than `at_seconds`? Retry from the very first frame.
        try:
            cmd[cmd.index('-ss') + 1] = '0'
            subprocess.run(cmd, check=True, timeout=120,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return None
    return _finalize(out_path) if os.path.exists(out_path) else None
