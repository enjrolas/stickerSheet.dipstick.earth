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
