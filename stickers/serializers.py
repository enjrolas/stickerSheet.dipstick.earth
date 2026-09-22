from rest_framework import serializers

from .models import Species, Sticker


class SpeciesSerializer(serializers.ModelSerializer):
    sticker_count = serializers.IntegerField(source='published_count',
                                             read_only=True)

    class Meta:
        model = Species
        fields = ('id', 'common_name', 'scientific_name', 'slug', 'group',
                  'notes', 'sticker_count')


class StickerSerializer(serializers.ModelSerializer):
    """Read representation. Deliberately omits submitter_email."""

    species = SpeciesSerializer(read_only=True)
    media_url = serializers.SerializerMethodField()
    sticker_png = serializers.CharField(source='sticker_url', read_only=True)
    thumb = serializers.CharField(source='thumb_url', read_only=True)
    lowres = serializers.CharField(source='lowres_url', read_only=True)
    poster = serializers.CharField(source='poster_url', read_only=True)
    caption_line = serializers.CharField(source='display_caption',
                                         read_only=True)
    # The sticker as vector, plus the bare outline it was cut with.
    svg = serializers.SerializerMethodField()
    svg_embedded = serializers.SerializerMethodField()
    shape = serializers.CharField(source='resolved_shape', read_only=True)
    shape_svg = serializers.CharField(source='shape_svg_url', read_only=True)
    shape_mask = serializers.CharField(source='shape_mask_url', read_only=True)

    class Meta:
        model = Sticker
        fields = ('id', 'slug', 'species', 'media_url', 'media_kind',
                  'sticker_png', 'svg', 'svg_embedded', 'shape', 'shape_svg',
                  'shape_mask', 'thumb', 'lowres', 'poster', 'caption',
                  'caption_line', 'wildlife_investigator', 'location',
                  'latitude', 'longitude', 'captured_at', 'created_at')

    def get_media_url(self, obj):
        return obj.media.url if obj.media else ''

    def _svg_url(self, obj, query=''):
        from django.urls import reverse
        try:
            url = reverse('api:sticker-svg', args=[obj.slug])
        except Exception:
            return ''
        request = self.context.get('request')
        return request.build_absolute_uri(url + query) if request else url + query

    def get_svg(self, obj):
        """Links to the artwork on this server — small response."""
        return self._svg_url(obj)

    def get_svg_embedded(self, obj):
        """Artwork inlined as a data URI — the file stands on its own."""
        return self._svg_url(obj, '?embed=1')


class StickerSubmitSerializer(serializers.ModelSerializer):
    """
    Write representation for the open endpoint.

    `species_name` is free text so a submitter never has to know our IDs; it
    resolves to an existing Species or creates one. `status` is NOT writable —
    everything lands pending.
    """

    species_name = serializers.CharField(max_length=120, write_only=True)

    class Meta:
        model = Sticker
        fields = ('species_name', 'media', 'caption', 'wildlife_investigator',
                  'location', 'captured_at', 'submitter_email')

    def validate_media(self, value):
        from .forms import validate_upload
        validate_upload(value)
        return value

    def create(self, validated_data):
        name = validated_data.pop('species_name').strip()
        # Case-insensitive match, or a new Species. Not get_or_create: that
        # rejects an `__iexact` lookup when it falls through to create().
        species = Species.objects.filter(common_name__iexact=name).first()
        if species is None:
            species = Species.objects.create(common_name=name)
        return Sticker.objects.create(
            species=species, status=Sticker.Status.PENDING, **validated_data)
