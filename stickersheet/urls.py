from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('stickers.api_urls')),
    path('', include('stickers.urls')),
]

# Apache serves /media/ and /static/ via Alias in production; this is only for
# `runserver`, where DEBUG is on.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
