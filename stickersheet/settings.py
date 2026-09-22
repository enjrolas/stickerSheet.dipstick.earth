"""
Settings for stickerSheet.dipstick.earth.

Secrets and production flags live in `local_settings.py` (gitignored), which is
imported at the bottom of this file. That is the same pattern as
workshops.dipstick.earth and is deliberate: mod_wsgi makes env-var plumbing
awkward, so a Python file apache can just import is the path of least pain.
See local_settings.py.example for the template.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Overridden in local_settings.py on production.
SECRET_KEY = 'django-insecure-dev-only-replace-me-in-local-settings'
DEBUG = False
ALLOWED_HOSTS = ['dipstick.earth', 'www.dipstick.earth',
                 'stickersheet.dipstick.earth', 'stickerSheet.dipstick.earth',
                 'localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'stickers',
    'pages',
]

MIDDLEWARE = [
    # First: everything downstream, including the throttle, should see the
    # real client address rather than a Cloudflare edge.
    'stickers.middleware.CloudflareRealIPMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'stickersheet.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'stickersheet.wsgi.application'

# MySQL. Password comes from local_settings.py; the default here is the dev
# credential so a fresh checkout can at least try to connect.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'stickerSheet',
        'USER': 'stickerSheet',
        'PASSWORD': '',
        'HOST': '127.0.0.1',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Content-hashed static filenames (style.a1b2c3d4.css).
#
# The vhost sets Cache-Control: max-age=604800 on /static/, and Cloudflare
# fronts this origin — so with plain filenames an edited stylesheet keeps
# serving the old bytes for up to a week. That already happened: a rebuilt
# framer.js came back `cf-cache-status: HIT, age: 25710` while the local file
# had changed. Hashing means new content is a new URL, so the long cache is
# correct instead of dangerous.
#
# Note this makes collectstatic strict: a {% static %} path or a CSS url()
# that does not resolve becomes a hard error rather than a silent 404.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Uploads: dipstick footage is phone-sized. Keep the whole file in memory below
# 5 MB, spool to disk above that, and hard-cap in the form (see stickers/forms.py).
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Uploads land in media/captures/<year>/<month>/, and those directories get
# created on the fly — by apache for a public submission, by `japhy` for a
# shell import. Without these, Django makes them 0o700/0o600 minus the umask
# and whichever user did NOT create them can no longer write there. That is a
# real 500 this site already hit: media/ itself was group-writable but the
# dated subdirectories underneath were not.
# The dirs also carry the setgid bit on disk so new ones stay group www-data.
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o775
FILE_UPLOAD_PERMISSIONS = 0o664

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 60,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Open submission endpoint. Generous enough for a workshop full of
        # people on one venue NAT, tight enough to make scripted spam boring.
        'submit': '12/hour',
    },
}

# The gallery is meant to be embeddable from dipstick.earth's own pages.
CORS_ALLOWED_ORIGINS = [
    'https://dipstick.earth',
    'https://workshops.dipstick.earth',
]
CORS_ALLOW_METHODS = ['GET', 'HEAD', 'OPTIONS']

CSRF_TRUSTED_ORIGINS = [
    'https://dipstick.earth',
    'https://www.dipstick.earth',
    'https://stickersheet.dipstick.earth',
]

# Search and the group-filter chips are hidden for now — the sheet is small
# enough that they are noise. The filtering itself still works from the URL
# (?q= and ?group=) and through the API; this only controls the UI. Flip to
# True to bring both back, on the sheet and on the sticker detail page.
STICKER_SHEET_SHOW_FILTERS = False

# --- Sticker pipeline knobs -------------------------------------------------
STICKER_PNG_SIZE = 1024       # die-cut PNG, square, transparent
STICKER_THUMB_WIDTH = 640     # grid thumbnail
STICKER_LOWRES_WIDTH = 32     # LQIP placeholder
STICKER_BORDER_RATIO = 0.055  # vinyl border as a fraction of the sticker size

# Nominatim asks for a contactable UA on every request.
GEOCODER_USER_AGENT = 'stickerSheet.dipstick.earth (alex@alexhornstein.com)'

# Django's default logging only mails ADMINS, so with DEBUG=False and no
# mail configured a 500 leaves NO traceback anywhere — the apache log shows
# only mod_wsgi chatter. Write tracebacks to a file instead.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': '/home/japhy/logs/stickersheet-django.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django.request': {'handlers': ['file'], 'level': 'ERROR',
                           'propagate': False},
        'stickers': {'handlers': ['file'], 'level': 'INFO', 'propagate': False},
    },
}

try:
    from .local_settings import *  # noqa: F401,F403
except ImportError:
    pass
