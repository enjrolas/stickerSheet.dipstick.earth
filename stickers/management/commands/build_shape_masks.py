"""
Turn each SVG outline in stickers/shapes/ into the two files the gallery needs.

The die-cut PNG is rendered server-side per upload, but the *gallery* has to
crop live media — a video or an animated GIF — which Pillow can't do. So the
browser does it with a CSS mask, and this command produces the mask.

For each shape, into stickers/static/stickers/shapes/:

  <slug>.svg        the outline itself, white fill + ink keyline, drawn behind
                    the media as the vinyl border
  <slug>.mask.png   the same silhouette INSET by the border width, as pure
                    alpha — this is what `mask-image` clips the media to

Run after adding or editing a shape, then collectstatic:

    .venv/bin/python manage.py build_shape_masks
    .venv/bin/python manage.py collectstatic --noinput
"""

import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image

from ... import shapes

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
            built += 1
            self.stdout.write('  %-22s %s' % (slug, label))

        self.stdout.write(self.style.SUCCESS(
            'Built %d shape masks in %s' % (built, OUT_DIR)))
