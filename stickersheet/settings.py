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
DEBUG = True
ALLOWED_HOSTS = ['stickersheet.dipstick.earth', 'stickerSheet.dipstick.earth',
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
]

MIDDLEWARE = [
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

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Uploads: dipstick footage is phone-sized. Keep the whole file in memory below
# 5 MB, spool to disk above that, and hard-cap in the form (see stickers/forms.py).
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

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
    'https://stickersheet.dipstick.earth',
    'https://dipstick.earth',
]

# --- Sticker pipeline knobs -------------------------------------------------
STICKER_PNG_SIZE = 1024       # die-cut PNG, square, transparent
STICKER_THUMB_WIDTH = 640     # grid thumbnail
STICKER_LOWRES_WIDTH = 32     # LQIP placeholder
STICKER_BORDER_RATIO = 0.055  # vinyl border as a fraction of the sticker size

# Nominatim asks for a contactable UA on every request.
GEOCODER_USER_AGENT = 'stickerSheet.dipstick.earth (alex@alexhornstein.com)'

try:
    from .local_settings import *  # noqa: F401,F403
except ImportError:
    pass
