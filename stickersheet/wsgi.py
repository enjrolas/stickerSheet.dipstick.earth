"""
WSGI config for stickerSheet.dipstick.earth.

Apache runs this under mod_wsgi in daemon mode. `touch` this file to recycle
the daemon after a code or template change.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stickersheet.settings')

application = get_wsgi_application()
