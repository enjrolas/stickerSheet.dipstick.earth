"""
End-to-end coverage of the bits most likely to break quietly: the moderation
gate, the derivative pipeline, and the shape of the public API.
"""

import io
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Species, Sticker

MEDIA = tempfile.mkdtemp(prefix='stickertest-')


def a_photo(name='crab.jpg', size=(1600, 1200)):
    buf = io.BytesIO()
    Image.new('RGB', size, (31, 120, 140)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


# Geocoding hits the network; stub it out for every test in this module.
@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=(37.4956, -122.4986))
class StickerPipelineTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _sticker(self, **kwargs):
        species = Species.objects.create(common_name='Purple shore crab')
        defaults = dict(species=species, media=a_photo(),
                        wildlife_investigator='Ada L.',
                        location='Pillar Point, California')
        defaults.update(kwargs)
        return Sticker.objects.create(**defaults)

    def test_derivatives_are_built_on_save(self, _geo):
        s = self._sticker()
        for suffix in ('.sticker.png', '.thumb.jpg', '.lowres.jpg'):
            path = s._derivative_path(suffix)
            self.assertTrue(os.path.exists(path), '%s was not built' % suffix)
        png = Image.open(s._derivative_path('.sticker.png'))
        self.assertEqual(png.mode, 'RGBA')
        self.assertEqual(png.getpixel((2, 2))[3], 0, 'corner should be cut away')
        self.assertEqual(png.getpixel((512, 512))[3], 255, 'middle should be opaque')

    def test_location_is_geocoded_once(self, geo):
        s = self._sticker()
        self.assertAlmostEqual(s.latitude, 37.4956, places=3)
        self.assertEqual(geo.call_count, 1)
        s.caption = 'sidestepping'
        s.save()
        self.assertEqual(geo.call_count, 1, 'unchanged location must not re-geocode')

    def test_submissions_land_pending_and_stay_off_the_sheet(self, _geo):
        response = self.client.post(reverse('stickers:submit'), {
            'species_name': 'Giant Pacific octopus',
            'media': a_photo('octopus.jpg'),
            'wildlife_investigator': 'Ada L.',
            'location': 'Pillar Point, California',
        })
        self.assertRedirects(response, reverse('stickers:submitted'))
        sticker = Sticker.objects.get()
        self.assertEqual(sticker.status, Sticker.Status.PENDING)
        self.assertNotContains(self.client.get(reverse('stickers:sheet')),
                               'Giant Pacific octopus')

    def test_publishing_puts_it_on_the_sheet(self, _geo):
        s = self._sticker()
        self.assertNotContains(self.client.get(reverse('stickers:sheet')),
                               'Purple shore crab')
        s.status = Sticker.Status.PUBLISHED
        s.save()
        self.assertContains(self.client.get(reverse('stickers:sheet')),
                            'Purple shore crab')

    def test_honeypot_rejects_bots(self, _geo):
        response = self.client.post(reverse('stickers:submit'), {
            'species_name': 'Spam crab',
            'media': a_photo(),
            'website': 'http://buy-things.example',
        })
        self.assertEqual(response.status_code, 200)  # redisplayed, not saved
        self.assertFalse(Sticker.objects.exists())

    def test_bad_file_type_is_refused(self, _geo):
        response = self.client.post(reverse('stickers:submit'), {
            'species_name': 'Crab',
            'media': SimpleUploadedFile('payload.exe', b'MZ',
                                        content_type='application/octet-stream'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sticker.objects.exists())

    def test_species_name_matches_case_insensitively(self, _geo):
        Species.objects.create(common_name='Purple Shore Crab')
        self.client.post(reverse('stickers:submit'), {
            'species_name': 'purple shore crab',
            'media': a_photo(),
        })
        self.assertEqual(Species.objects.count(), 1, 'should reuse the species')


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class ApiTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_list_returns_only_published(self, _geo):
        species = Species.objects.create(common_name='Blenny')
        Sticker.objects.create(species=species, media=a_photo(),
                               status=Sticker.Status.PUBLISHED)
        Sticker.objects.create(species=species, media=a_photo('b.jpg'),
                               status=Sticker.Status.PENDING)
        data = self.client.get('/api/stickers/').json()
        self.assertEqual(data['count'], 1)

    def test_submitter_email_is_never_exposed(self, _geo):
        species = Species.objects.create(common_name='Blenny')
        Sticker.objects.create(species=species, media=a_photo(),
                               status=Sticker.Status.PUBLISHED,
                               submitter_email='private@example.com')
        body = self.client.get('/api/stickers/').content.decode()
        self.assertNotIn('private@example.com', body)

    def test_api_submit_creates_pending(self, _geo):
        response = self.client.post('/api/submit/', {
            'species_name': 'Sea star',
            'media': a_photo('star.jpg'),
            'wildlife_investigator': 'Ada L.',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PENDING)

    def test_api_cannot_publish_itself(self, _geo):
        self.client.post('/api/submit/', {
            'species_name': 'Sea star',
            'media': a_photo('star.jpg'),
            'status': 'published',
        })
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PENDING)

    def test_filtering_by_species_slug(self, _geo):
        crab = Species.objects.create(common_name='Crab')
        fish = Species.objects.create(common_name='Fish')
        Sticker.objects.create(species=crab, media=a_photo(),
                               status=Sticker.Status.PUBLISHED)
        Sticker.objects.create(species=fish, media=a_photo('f.jpg'),
                               status=Sticker.Status.PUBLISHED)
        data = self.client.get('/api/stickers/?species=crab').json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['species']['common_name'], 'Crab')
