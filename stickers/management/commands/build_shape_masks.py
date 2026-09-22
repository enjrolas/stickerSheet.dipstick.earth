"""
Turn each SVG outline in stickers/shapes/ into the two files the gallery needs.

The die-cut PNG is rendered server-side per upload, but the *gallery* has to
crop live media — a video or an animated GIF — which Pillow can't do. So the
browser does it with a CSS mask, and this command produces the mask.

For each shape, into stickers/static/stickers/shapes/:

  <slug>.svg          the source outline, kept for /api/shapes/ and anyone
                      who wants the vector
  <slug>.outline.png  white vinyl body + ink keyline, transparent outside —
                      what the framing preview paints BEHIND the media
  <slug>.ring.png     the same art with the middle punched out, so it can sit
                      ON TOP of the picture. Needed once the die-cut window
                      turns (animal disco): a picture in front of the vinyl
                      can swing past the orbiting edge and escape the sticker,
                      where one behind a ring is always framed by it.
  <slug>.mask.png     the same silhouette INSET by the border width, as pure
                      alpha — what `mask-image` clips the media to

The outline is rendered here, by the same shapes.mask() the server cuts with,
rather than left to the browser to rasterise from the SVG. Browsers and SVG
rasterisers disagree about stroke overflow and viewBox fitting, and any
disagreement shows up as a preview that does not match the finished sticker.

Run after adding or editing a shape, then collectstatic:

    .venv/bin/python manage.py build_shape_masks
    .venv/bin/python manage.py collectstatic --noinput
"""

import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, ImageChops

from ... import imaging, shapes

OUT_DIR = os.path.join(os.path.dirname(shapes.__file__),
                       'static', 'stickers', 'shapes')
MASK_SIZE = 512


class Command(BaseCommand):
    help = 'Build CSS mask PNGs from the SVG sticker outlines.'

    def add_arguments(self, parser):
        parser.add_argument('--size', type=int, default=MASK_SIZE)

    def handle(self, *args, **options):
        size = options['size']
        os.makedirs(OUT_DIR, exist_ok=True)
        border = int(size * settings.STICKER_BORDER_RATIO)
        built = 0

        for slug, label in shapes.available():
            src = os.path.join(shapes.SHAPE_DIR, '%s.svg' % slug)
            shutil.copyfile(src, os.path.join(OUT_DIR, '%s.svg' % slug))

            points = shapes.load(slug)
            if not points:
                self.stderr.write('could not parse %s' % slug)
                continue

            # Pure-alpha silhouette: white where the media shows through.
            inset = shapes.mask(points, size, inset=border)
            png = Image.new('RGBA', (size, size), (255, 255, 255, 0))
            png.putalpha(inset)
            png.save(os.path.join(OUT_DIR, '%s.mask.png' % slug),
                     'PNG', optimize=True)

            # The vinyl body plus the ink keyline, built exactly as
            # imaging.make_diecut builds them so the preview cannot drift.
            keyline = max(1, int(size * imaging.KEYLINE_RATIO))
            outer = shapes.mask(points, size)
            ring = ImageChops.subtract(outer, shapes.mask(points, size,
                                                          inset=keyline))
            outline = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            outline.paste(Image.new('RGBA', (size, size), imaging.VINYL),
                          (0, 0), outer)
            outline.paste(Image.new('RGBA', (size, size), imaging.INK),
                          (0, 0), ring)
            outline.save(os.path.join(OUT_DIR, '%s.outline.png' % slug),
                         'PNG', optimize=True)

            # Same art, middle removed: alpha becomes the band between the
            # outline and the inset, which is exactly the vinyl plus keyline.
            ring = outline.copy()
            ring.putalpha(ImageChops.subtract(outer, inset))
            ring.save(os.path.join(OUT_DIR, '%s.ring.png' % slug),
                      'PNG', optimize=True)
            built += 1
            self.stdout.write('  %-22s %s' % (slug, label))

        self.stdout.write(self.style.SUCCESS(
            'Built %d shape masks in %s' % (built, OUT_DIR)))
