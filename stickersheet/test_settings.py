"""
Test settings.

Prefer running the suite against MySQL, so it exercises the same engine as
production:

    GRANT ALL PRIVILEGES ON `test_stickerSheet`.* TO 'stickerSheet'@'%';

Until that grant exists, `--settings=stickersheet.test_settings` runs the suite
on an in-memory SQLite database instead. That is fast and covers the logic, but
it will NOT catch MySQL-specific problems (utf8mb4 collation, strict-mode
errors, index length limits). Treat a green run here as necessary, not
sufficient, before a schema change.
"""

from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Force local storage. settings.py imports local_settings at the end, and that
# is where USE_S3 lives — so without this the suite runs against the REAL S3
# bucket. It already did once, on 2026-09-22, littering ~180 fixture objects
# (crab_*, star_*, octopus…) into live media. Tests must never touch it.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# Belt and braces: if anything reconstructs a client from these, it fails fast
# and loudly rather than authenticating against the real account.
AWS_ACCESS_KEY_ID = 'testing-not-a-real-key'
AWS_SECRET_ACCESS_KEY = 'testing-not-a-real-secret'

