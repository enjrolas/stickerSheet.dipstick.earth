"""
The sheet is made of Stickers. A Sticker is one animal, photographed or filmed
down a dipstick by one person, in one place.

Uploads are public (see forms.py / api.py) and land as PENDING. Nothing reaches
the sheet until a staff user flips it to PUBLISHED in the admin.
"""

import os

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from . import imaging
from .geocode import geocode


class Species(models.Model):
    """A kind of animal. Stickers group by this on the sheet."""

    class Group(models.TextChoices):
        FISH = 'fish', 'Fish'
        INVERTEBRATE = 'invertebrate', 'Invertebrate'
        AMPHIBIAN = 'amphibian', 'Amphibian'
        REPTILE = 'reptile', 'Reptile'
        BIRD = 'bird', 'Bird'
        MAMMAL = 'mammal', 'Mammal'
        PLANT = 'plant', 'Plant or algae'
        OTHER = 'other', 'Something else'

    common_name = models.CharField(max_length=120, unique=True)
    scientific_name = models.CharField(max_length=160, blank=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    group = models.CharField(max_length=20, choices=Group.choices,
                             default=Group.OTHER)
    notes = models.TextField(
        blank=True,
        help_text='Optional blurb shown on the species page.')

    class Meta:
        verbose_name_plural = 'species'
        ordering = ['common_name']

    def __str__(self):
        return self.common_name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.common_name)[:140]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('stickers:species', args=[self.slug])

    @property
    def published_count(self):
        return self.stickers.filter(status=Sticker.Status.PUBLISHED).count()


def upload_to(instance, filename):
    """media/captures/<year>/<month>/<filename>"""
    now = timezone.now()
    return os.path.join('captures', str(now.year), '%02d' % now.month, filename)


class Sticker(models.Model):
    """One wildlife capture, turned into a die-cut sticker."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        PUBLISHED = 'published', 'Published'
        REJECTED = 'rejected', 'Rejected'

    class MediaKind(models.TextChoices):
        IMAGE = 'image', 'Photo'
        VIDEO = 'video', 'Video'

    # --- what was captured ---
    species = models.ForeignKey(Species, on_delete=models.PROTECT,
                                related_name='stickers')
    media = models.FileField(upload_to=upload_to)
    media_kind = models.CharField(max_length=10, choices=MediaKind.choices,
                                  default=MediaKind.IMAGE, editable=False)
    caption = models.CharField(max_length=280, blank=True)

    # --- who and where ---
    wildlife_investigator = models.CharField(
        max_length=120, blank=True,
        help_text='Who pointed the dipstick. Shown on the sticker back.')
    location = models.CharField(
        max_length=200, blank=True,
        help_text='Free text — geocoded to lat/lng on save.')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    captured_at = models.DateField(null=True, blank=True)

    # --- moderation ---
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    submitter_email = models.EmailField(
        blank=True,
        help_text='Optional, private. Never rendered in a template.')
    moderator_note = models.TextField(blank=True)

    slug = models.SlugField(max_length=160, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return '%s (%s)' % (self.species, self.wildlife_investigator or 'anon')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot so save() knows whether to re-geocode / rebuild derivatives.
        # Same trick as media_carousel on workshops.dipstick.earth.
        self._original_location = self.location
        self._original_media = self.media.name if self.media else None

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify('%s-%s' % (self.species_id and str(self.species) or 'sticker',
                                      self.wildlife_investigator or ''))[:140] or 'sticker'
            self.slug = base
        if self.media:
            self.media_kind = (self.MediaKind.VIDEO
                               if imaging.is_video(self.media.name)
                               else self.MediaKind.IMAGE)

        # `_state.adding` must be read BEFORE super().save() flips it. On a
        # new row the comparisons below can't work on their own: upload_to
        # rewrites media.name during save, and __init__ already snapshotted
        # the incoming location — so both would compare equal and we'd never
        # build derivatives or geocode a first save.
        is_new = self._state.adding
        media_changed = bool(self.media) and (
            is_new or self.media.name != self._original_media)
        location_changed = bool(self.location) and (
            is_new or self.location != self._original_location)

        super().save(*args, **kwargs)

        # Unique slug needs the pk, so fix it up after the first insert.
        if self.slug and not self.slug.endswith('-%d' % self.pk):
            candidate = '%s-%d' % (self.slug[:150], self.pk)
            if candidate != self.slug:
                Sticker.objects.filter(pk=self.pk).update(slug=candidate)
                self.slug = candidate

        if location_changed:
            self._geocode()
        if media_changed:
            self.build_derivatives()

        self._original_location = self.location
        self._original_media = self.media.name if self.media else None

    def _geocode(self):
        """Nominatim lookup. Silently no-ops on any network trouble."""
        point = geocode(self.location)
        if point:
            self.latitude, self.longitude = point
            Sticker.objects.filter(pk=self.pk).update(
                latitude=self.latitude, longitude=self.longitude)

    # --- derivative files -------------------------------------------------
    # Built synchronously in save(). Each *_url property lazily rebuilds if the
    # file has gone missing, so a derivative that failed to write (wrong user,
    # full disk) is backfilled on first access instead of 404ing forever.

    def _derivative_path(self, suffix):
        if not self.media:
            return None
        base, _ = os.path.splitext(self.media.path)
        return base + suffix

    def _derivative_url(self, suffix):
        if not self.media:
            return ''
        base, _ = os.path.splitext(self.media.url)
        return base + suffix

    def build_derivatives(self):
        """Make the die-cut PNG, thumbnail, LQIP and (for video) a poster."""
        if not self.media:
            return
        try:
            source = self.media.path
            if self.media_kind == self.MediaKind.VIDEO:
                source = imaging.video_poster(
                    self.media.path, self._derivative_path('.poster.jpg'))
                if not source:
                    return
            imaging.make_thumb(source, self._derivative_path('.thumb.jpg'),
                               settings.STICKER_THUMB_WIDTH)
            imaging.make_lowres(source, self._derivative_path('.lowres.jpg'),
                                settings.STICKER_LOWRES_WIDTH)
            imaging.make_diecut(source, self._derivative_path('.sticker.png'),
                                settings.STICKER_PNG_SIZE,
                                settings.STICKER_BORDER_RATIO)
        except Exception:
            # A corrupt upload must not 500 the submit form. The properties
            # below fall back to the original file.
            pass

    def _lazy(self, suffix, builder_needed=True):
        path = self._derivative_path(suffix)
        if path and not os.path.exists(path) and builder_needed:
            self.build_derivatives()
        if path and os.path.exists(path):
            return self._derivative_url(suffix)
        return ''

    @property
    def poster_url(self):
        if self.media_kind != self.MediaKind.VIDEO:
            return self.media.url if self.media else ''
        return self._lazy('.poster.jpg') or ''

    @property
    def thumb_url(self):
        return self._lazy('.thumb.jpg') or (self.media.url if self.media else '')

    @property
    def lowres_url(self):
        return self._lazy('.lowres.jpg') or ''

    @property
    def sticker_url(self):
        """The downloadable die-cut PNG."""
        return self._lazy('.sticker.png') or ''

    # --- display ----------------------------------------------------------
    def get_absolute_url(self):
        return reverse('stickers:detail', args=[self.slug])

    @property
    def display_caption(self):
        """'<caption>, spotted by <investigator> in <location>' — skipping blanks."""
        parts = []
        if self.caption:
            parts.append(self.caption)
        if self.wildlife_investigator:
            parts.append('spotted by %s' % self.wildlife_investigator)
        if self.location:
            parts.append('in %s' % self.location)
        return ', '.join(parts)

    @property
    def is_video(self):
        return self.media_kind == self.MediaKind.VIDEO
