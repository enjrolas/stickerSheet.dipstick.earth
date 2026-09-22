"""
Settings with S3 forced on, for the one-off migration.

Used so `migrate_media_to_s3` can upload while the LIVE app is still serving
from local disk. Flipping USE_S3 in local_settings.py first would leave a
window where stickers point at S3 keys that have not been uploaded yet — the
daemon recycles on its own, so that window is not under our control.

    .venv/bin/python manage.py migrate_media_to_s3 --settings=stickersheet.s3_settings
"""

from .settings import *  # noqa: F401,F403
from .local_settings import S3_STORAGES

STORAGES = S3_STORAGES
