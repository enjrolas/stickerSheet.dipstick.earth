"""Site-wide template context."""

from django.conf import settings


def analytics(request):
    """
    The Google Analytics measurement ID, or nothing.

    Returns nothing — so the tag is not rendered at all — in three cases:

      * DEBUG is on, so local work does not pollute the numbers
      * the visitor is staff, for the same reason: your own visits to your
        own site are the single biggest source of junk in a small site's
        analytics, and you visit it far more than anyone else
      * the ID is unset

    The measurement ID is not a secret (it is visible in the page source of
    every site that uses one), so it lives in settings.py rather than
    local_settings.py and travels with the repo.
    """
    if settings.DEBUG or not getattr(settings, 'GOOGLE_ANALYTICS_ID', ''):
        return {'google_analytics_id': ''}
    if request.user.is_authenticated and request.user.is_staff:
        return {'google_analytics_id': ''}
    return {'google_analytics_id': settings.GOOGLE_ANALYTICS_ID}
