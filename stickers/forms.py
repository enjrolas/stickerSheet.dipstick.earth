import os

from django import forms
from django.core.exceptions import ValidationError

from . import imaging, shapes
from .models import Species, Sticker

MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # 64 MB — phone video off a dipstick
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.webp', '.gif',
                      '.mp4', '.mov', '.m4v', '.webm'}


def validate_upload(f):
    """Shared by the HTML form and the API serializer."""
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            'That file type is not supported. Photos (jpg, png, heic, webp) '
            'and video (mp4, mov, webm) only.')
    if f.size > MAX_UPLOAD_BYTES:
        raise ValidationError('That file is larger than 64 MB. Trim the clip '
                              'or send a photo instead.')
    return f


class SubmitStickerForm(forms.ModelForm):
    """
    The public submit form. Anything it creates is PENDING — `status` is not a
    field here, so it cannot be set from the outside.
    """

    species_name = forms.CharField(
        max_length=120, label='What is it?',
        help_text="Common name is fine — 'purple shore crab', 'unknown blenny'.",
        widget=forms.TextInput(attrs={'placeholder': 'purple shore crab',
                                      'autocomplete': 'off'}))

    # Honeypot: a real person never fills this in, bots fill everything.
    website = forms.CharField(required=False, widget=forms.HiddenInput,
                              label='')

    class Meta:
        model = Sticker
        # shape/focal_x/focal_y/zoom are driven by the framing editor and
        # rendered as hidden inputs; they are safe to accept because each is
        # validated below and none of them can affect moderation.
        fields = ('media', 'shape', 'focal_x', 'focal_y', 'zoom', 'caption',
                  'wildlife_investigator', 'location', 'captured_at',
                  'submitter_email')
        labels = {
            'media': 'Photo or video',
            'caption': 'Caption',
            'wildlife_investigator': 'Your name',
            'location': 'Where was it?',
            'captured_at': 'When?',
            'submitter_email': 'Your email',
        }
        help_texts = {
            'caption': 'One line. Shown under the sticker.',
            'wildlife_investigator': 'Goes on the sticker as the credit.',
            'location': "Anywhere Google would find — 'Pillar Point, CA'.",
            'submitter_email': 'Private. Only so we can reach you about this '
                               'submission. Never shown on the site.',
        }
        widgets = {
            'shape': forms.HiddenInput(),
            'focal_x': forms.HiddenInput(),
            'focal_y': forms.HiddenInput(),
            'zoom': forms.HiddenInput(),
            'captured_at': forms.DateInput(attrs={'type': 'date'}),
            'caption': forms.TextInput(
                attrs={'placeholder': 'sidestepping under a rock'}),
            'location': forms.TextInput(
                attrs={'placeholder': 'Pillar Point, California'}),
            'wildlife_investigator': forms.TextInput(
                attrs={'placeholder': 'Ada L.'}),
        }

    def clean_shape(self):
        """Only an outline we actually ship; blank means let the server pick."""
        value = (self.cleaned_data.get('shape') or '').strip()
        if not value:
            return ''
        if value not in [slug for slug, _ in shapes.available()]:
            raise ValidationError('That is not one of the sticker shapes.')
        return value

    def _clean_unit(self, name):
        value = self.cleaned_data.get(name)
        if value is None:
            return 0.5
        return min(max(float(value), 0.0), 1.0)

    def clean_focal_x(self):
        return self._clean_unit('focal_x')

    def clean_focal_y(self):
        return self._clean_unit('focal_y')

    def clean_zoom(self):
        value = self.cleaned_data.get('zoom')
        if value is None:
            return 1.0
        # Below 1.0 is zoomed out (padded, not cropped). Same range as the
        # slider and as imaging.focal_crop.
        return min(max(float(value), imaging.MIN_ZOOM), imaging.MAX_ZOOM)

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise ValidationError('Nope.')
        return ''

    def clean_media(self):
        return validate_upload(self.cleaned_data['media'])

    def save(self, commit=True):
        sticker = super().save(commit=False)
        name = self.cleaned_data['species_name'].strip()
        species = Species.objects.filter(common_name__iexact=name).first()
        if species is None:
            species = Species.objects.create(common_name=name)
        sticker.species = species
        sticker.status = Sticker.Status.PENDING
        if commit:
            sticker.save()
        return sticker


class ReframeForm(forms.ModelForm):
    """
    Staff-only re-cut of an existing sticker.

    Deliberately narrow: only the framing. Status, media and credits are not
    here, so a re-frame cannot accidentally publish something or rewrite who
    took the picture.
    """

    class Meta:
        model = Sticker
        fields = ('shape', 'focal_x', 'focal_y', 'zoom')
        widgets = {
            'shape': forms.HiddenInput(),
            'focal_x': forms.HiddenInput(),
            'focal_y': forms.HiddenInput(),
            'zoom': forms.HiddenInput(),
        }

    clean_shape = SubmitStickerForm.clean_shape
    _clean_unit = SubmitStickerForm._clean_unit
    clean_focal_x = SubmitStickerForm.clean_focal_x
    clean_focal_y = SubmitStickerForm.clean_focal_y
    clean_zoom = SubmitStickerForm.clean_zoom
