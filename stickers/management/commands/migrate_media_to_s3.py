"""
Copy existing uploads and derivatives from local disk into the configured
storage (S3), then verify each one is readable back.

Run AFTER pointing STORAGES at S3 in local_settings.py. It reads the old files
straight off the filesystem — it does not go through Django storage for the
source, because by then `default_storage` is already S3.

    .venv/bin/python manage.py migrate_media_to_s3 --dry-run
    .venv/bin/python manage.py migrate_media_to_s3

Nothing local is deleted. Check the site works, then remove the old tree by
hand once you are satisfied.
"""

import os

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from ...models import Sticker

SUFFIXES = ('.sticker.png', '.thumb.jpg', '.lowres.jpg', '.poster.jpg')


class Command(BaseCommand):
    help = 'Copy local media into the configured storage backend.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry = options['dry_run']
        root = str(settings.MEDIA_ROOT)
        backend = default_storage.__class__.__name__
        self.stdout.write('storage backend: %s' % backend)
        if 'S3' not in backend and not dry:
            self.stdout.write(self.style.WARNING(
                'Storage is not S3 — this would copy files onto themselves. '
                'Point STORAGES at S3 first, or use --dry-run.'))
            return

        copied = skipped = failed = 0
        # all_objects: a sticker in the bin still owns its file, and the whole
        # point of soft delete is that the file survives.
        for sticker in Sticker.all_objects.all():
            if not sticker.media or not sticker.media.name:
                continue
            names = [sticker.media.name] + [
                sticker._derivative_name(s) for s in SUFFIXES]
            for name in names:
                if not name:
                    continue
                local = os.path.join(root, name)
                if not os.path.exists(local):
                    continue
                if default_storage.exists(name):
                    skipped += 1
                    continue
                if dry:
                    self.stdout.write('  would copy %s (%d bytes)'
                                      % (name, os.path.getsize(local)))
                    copied += 1
                    continue
                try:
                    with open(local, 'rb') as fh:
                        default_storage.save(name, File(fh))
                    # Read it straight back: a silent write failure here would
                    # mean the sticker points at a key that is not there.
                    if not default_storage.exists(name):
                        raise IOError('written but not readable back')
                    self.stdout.write('  %s' % name)
                    copied += 1
                except Exception as exc:
                    self.stderr.write('  FAILED %s: %s' % (name, exc))
                    failed += 1

        self.stdout.write(self.style.SUCCESS(
            '%s %d file(s), %d already there, %d failed'
            % ('would copy' if dry else 'copied', copied, skipped, failed)))
        if failed:
            self.stdout.write(self.style.WARNING(
                'Leave the local files in place until the failures are fixed.'))
