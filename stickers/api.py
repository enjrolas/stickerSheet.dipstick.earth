"""
Public JSON API.

Read is open to anyone (the sheet is the point). Write is one throttled
endpoint that only ever creates PENDING rows — publishing is a human decision
made in the admin.
"""

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.templatetags.static import static

from . import shapes, svg
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
    GET /api/stickers/              published stickers, newest first
    GET /api/stickers/<slug>/       one sticker
    GET /api/stickers/<slug>/svg/   that sticker as an SVG file

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


    @action(detail=True, methods=['get'], url_path='svg')
    def svg(self, request, slug=None):
        """
        The sticker as a standalone SVG.

        ?embed=1  inline the artwork as a data URI, so the file works on its
                  own with no callback to this server. Without it the <image>
                  links back here, which keeps the response tiny.
        ?download=1  send it as an attachment rather than rendering inline.
        """
        sticker = self.get_object()
        embed = request.query_params.get('embed') in ('1', 'true', 'yes')

        href = ''
        if not embed:
            target = sticker.poster_url if sticker.is_video else (
                sticker.media.url if sticker.media else '')
            if target:
                href = request.build_absolute_uri(target)

        source = svg.sticker_svg(sticker, href=href, embed=embed)
        if not source:
            raise Http404('No outline for this sticker yet.')

        response = HttpResponse(source, content_type='image/svg+xml')
        if request.query_params.get('download') in ('1', 'true', 'yes'):
            response['Content-Disposition'] = (
                'attachment; filename="%s.svg"' % (sticker.slug or sticker.pk))
        # The artwork is immutable once uploaded; the outline only changes if
        # a moderator picks a different one.
        response['Cache-Control'] = 'public, max-age=3600'
        return response


class ShapeViewSet(viewsets.ViewSet):
    """
    GET /api/shapes/ — the die-cut outlines a sticker can be cut with.

    Handy for a client that wants to offer the choice, or to fetch the bare
    silhouette. Reads the SVGs on disk, so a new outline appears here with no
    migration and no code change.
    """

    permission_classes = [AllowAny]

    def list(self, request):
        out = []
        for slug, label in shapes.available():
            out.append({
                'slug': slug,
                'label': label,
                'svg': request.build_absolute_uri(
                    static('stickers/shapes/%s.svg' % slug)),
                'mask_png': request.build_absolute_uri(
                    static('stickers/shapes/%s.mask.png' % slug)),
                'path': shapes.raw_path(slug),
            })
        return Response(out)


class SpeciesViewSet(mixins.ListModelMixin,
                     mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """GET /api/species/ — every species with at least one published sticker."""

    serializer_class = SpeciesSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return (Species.objects
                # NOTE: an annotation joins at the SQL level, so the
                # soft-delete manager does NOT apply here — the deleted_at
                # test has to be spelled out or binned stickers get counted.
                .annotate(n=Count('stickers', filter=Q(
                    stickers__status=Sticker.Status.PUBLISHED,
                    stickers__deleted_at__isnull=True)))
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
