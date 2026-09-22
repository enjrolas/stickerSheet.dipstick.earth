"""
Free-text location -> (lat, lng) via Nominatim, same as the workshops site.

Never raises: a network failure just means the sticker has no pin on the map.
Nominatim's usage policy asks for a real User-Agent and no more than 1 req/s;
this only runs on save, which is human-paced.
"""

import requests
from django.conf import settings

ENDPOINT = 'https://nominatim.openstreetmap.org/search'


def geocode(location, timeout=6):
    if not location:
        return None
    try:
        response = requests.get(
            ENDPOINT,
            params={'q': location, 'format': 'json', 'limit': 1},
            headers={'User-Agent': settings.GEOCODER_USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    except Exception:
        pass
    return None
