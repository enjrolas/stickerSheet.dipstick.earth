from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from stickers import views as stickers_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('stickers.api_urls')),

    # The sheet is /dipstickers/. It has moved twice — it was the root of its
    # own host, then /gallery/ — so both older forms still resolve rather than
    # breaking links people have already shared.
    path('dipstickers/', include('stickers.urls')),
    path('gallery/', RedirectView.as_view(url='/dipstickers/', permanent=True)),
    re_path(r'^gallery/(?P<rest>.*)$',
            RedirectView.as_view(url='/dipstickers/%(rest)s', permanent=True)),

    # Legacy .html URLs from the static site. People have these bookmarked and
    # they are in the wild on social, so keep them resolving.
    path('index.html', RedirectView.as_view(pattern_name='pages:index',
                                            permanent=True)),
    path('contacts.html', RedirectView.as_view(pattern_name='pages:contacts',
                                               permanent=True)),
    path('kickstarter/index.html',
         RedirectView.as_view(pattern_name='pages:kickstarter', permanent=True)),

    # Unlinked on purpose — reachable only if you know it is here.
    path('stickersheet/', stickers_views.sticker_sheet, name='sticker-sheet'),

    path('', include('pages.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
