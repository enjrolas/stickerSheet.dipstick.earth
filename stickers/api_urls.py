from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register('stickers', api.StickerViewSet, basename='sticker')
router.register('species', api.SpeciesViewSet, basename='species')
router.register('shapes', api.ShapeViewSet, basename='shape')
router.register('submit', api.SubmitViewSet, basename='submit')

app_name = 'api'

urlpatterns = [
    path('auth/token/', api.TokenView.as_view(), name='token'),
    path('auth/token/revoke/', api.RevokeTokenView.as_view(), name='token-revoke'),
    path('', include(router.urls)),
]
