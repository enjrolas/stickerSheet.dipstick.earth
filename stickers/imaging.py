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

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.avi', '.mkv', '.3gp'}

# The mask is drawn this many times oversized and then downsampled, which is
# what keeps the die-cut edge smooth instead of stair-stepped.
SUPERSAMPLE = 4

INK = (20, 18, 16, 255)      # --ink from style-sticker.css
VINYL = (255, 255, 255, 255)


def is_video(filename):
    return os.path.splitext(filename or '')[1].lower() in VIDEO_EXTENSIONS


def _open_upright(path):
    """Open an image with EXIF rotation already applied."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert('RGB')


def _square_crop(img):
    """Center-crop to a square without distorting."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _squircle_mask(size, radius_ratio=0.22):
    """An L-mask: rounded square, drawn oversized and downsampled."""
    big = size * SUPERSAMPLE
    mask = Image.new('L', (big, big), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, big - 1, big - 1),
                           radius=int(big * radius_ratio), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def make_diecut(source_path, out_path, size, border_ratio):
    """
    Write a transparent PNG sticker: photo, white vinyl border, ink keyline.

    `size` is the full square canvas; the border eats `border_ratio` of it on
    each side, so the photo itself lands in the middle.
    """
    if not out_path:
        return None

    border = max(2, int(size * border_ratio))
    keyline = max(1, int(size * 0.006))
    inner = size - 2 * border

    photo = _square_crop(_open_upright(source_path)).resize(
        (inner, inner), Image.LANCZOS)

    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))

    # The vinyl: a solid white squircle filling the canvas.
    outer_mask = _squircle_mask(size)
    canvas.paste(Image.new('RGBA', (size, size), VINYL), (0, 0), outer_mask)

    # A thin ink keyline just inside that edge, so the sticker still reads as
    # die-cut against a white or cream page. Built as the difference between
    # the outer squircle and one inset by `keyline`.
    inset = Image.new('L', (size, size), 0)
    inset.paste(_squircle_mask(size - 2 * keyline), (keyline, keyline))
    ring = ImageChops.subtract(outer_mask, inset)
    canvas.paste(Image.new('RGBA', (size, size), INK), (0, 0), ring)

    # The photo, masked to a slightly tighter squircle so the white reads as a
    # border rather than a frame.
    inner_mask = _squircle_mask(inner, radius_ratio=0.20)
    canvas.paste(photo.convert('RGBA'), (border, border), inner_mask)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas.save(out_path, 'PNG', optimize=True)
    return out_path


def make_thumb(source_path, out_path, width):
    """Grid thumbnail — square, JPEG, progressive."""
    if not out_path:
        return None
    img = _square_crop(_open_upright(source_path)).resize(
        (width, width), Image.LANCZOS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, 'JPEG', quality=85, optimize=True, progressive=True)
    return out_path


def make_lowres(source_path, out_path, width):
    """Tiny blurred LQIP placeholder, inlined-cheap at a couple of KB."""
    if not out_path:
        return None
    img = _square_crop(_open_upright(source_path)).resize(
        (width, width), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, 'JPEG', quality=60, optimize=True)
    return out_path


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
    return out_path if os.path.exists(out_path) else None
