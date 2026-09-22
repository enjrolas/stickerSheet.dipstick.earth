"""
Public JSON API.

Read is open to anyone (the sheet is the point). Write is one throttled
endpoint that only ever creates PENDING rows — publishing is a human decision
made in the admin.
"""

from django.db.models import Count, Q
from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Species, Sticker
from .serializers import (SpeciesSerializer, StickerSerializer,
                          StickerSubmitSerializer)


def published():
    return (Sticker.objects
            .filter(status=Sticker.Status.PUBLISHED)
            .select_related('species'))


class StickerViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """
    GET /api/stickers/            published stickers, newest first
    GET /api/stickers/<slug>/     one sticker

    Filters: ?species=<slug>  ?group=<group>  ?kind=image|video  ?q=<text>
    """

    serializer_class = StickerSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        qs = published()
        params = self.request.query_params
        if params.get('species'):
            qs = qs.filter(species__slug=params['species'])
        if params.get('group'):
            qs = qs.filter(species__group=params['group'])
        if params.get('kind'):
            qs = qs.filter(media_kind=params['kind'])
        if params.get('q'):
            term = params['q']
            qs = qs.filter(
                Q(species__common_name__icontains=term)
                | Q(species__scientific_name__icontains=term)
                | Q(caption__icontains=term)
                | Q(location__icontains=term)
                | Q(wildlife_investigator__icontains=term))
        return qs


class SpeciesViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """GET /api/species/ — every species with at least one published sticker."""

    serializer_class = SpeciesSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return (Species.objects
                .annotate(n=Count('stickers',
                                  filter=Q(stickers__status=Sticker.Status.PUBLISHED)))
                .filter(n__gt=0)
                .order_by('common_name'))


class SubmitViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    """
    POST /api/submit/ — multipart. Open, throttled, always lands PENDING.

    Fields: species_name, media, caption, wildlife_investigator, location,
            captured_at, submitter_email
    """

    serializer_class = StickerSubmitSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'submit'
    queryset = Sticker.objects.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sticker = serializer.save()
        return Response(
            {'ok': True,
             'id': sticker.pk,
             'status': sticker.status,
             'detail': 'Thanks — your sticker is in the queue for review.'},
            status=201)
