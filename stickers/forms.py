import os

from django import forms
from django.core.exceptions import ValidationError

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
        fields = ('media', 'caption', 'wildlife_investigator', 'location',
                  'captured_at', 'submitter_email')
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
            'captured_at': forms.DateInput(attrs={'type': 'date'}),
            'caption': forms.TextInput(
                attrs={'placeholder': 'sidestepping under a rock'}),
            'location': forms.TextInput(
                attrs={'placeholder': 'Pillar Point, California'}),
            'wildlife_investigator': forms.TextInput(
                attrs={'placeholder': 'Ada L.'}),
        }

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
