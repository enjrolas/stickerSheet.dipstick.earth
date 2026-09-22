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

from . import shapes, svg
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


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class ShapeTests(TestCase):
    """The SVG outlines, and the two files the gallery crops live media with."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_every_shipped_outline_parses(self, _geo):
        found = shapes.available()
        self.assertGreaterEqual(len(found), 10)
        for slug, _label in found:
            pts = shapes.load(slug)
            self.assertIsNotNone(pts, '%s did not parse' % slug)
            self.assertGreaterEqual(len(pts), 3)

    def test_inset_eats_inward_everywhere(self, _geo):
        """
        The border is a TRUE uniform inset, not a scale toward the centroid.

        On a starburst that distinction is the whole point: scaling keeps the
        spikes and just shortens them, so the photo still reached into the
        points and there was no white there. A uniform inset eats the narrow
        wedges away entirely, which is why the tip recedes by far more than
        the inset distance -- that recession IS the border at the spike.
        """
        pts = shapes.load('07-classic-starburst')
        outer = shapes.mask(pts, 256)
        inset = shapes.mask(pts, 256, inset=14)

        self.assertLess(sum(inset.getdata()), sum(outer.getdata()))
        # The shape must survive, not be eroded to nothing.
        self.assertGreater(sum(inset.getdata()), 0.25 * sum(outer.getdata()))

        # Strict subset: no inset pixel may sit where the outline is empty,
        # or the media would bleed outside its own die-cut.
        o, i = outer.load(), inset.load()
        for y in range(0, 256, 3):
            for x in range(0, 256, 3):
                if i[x, y] > 128:
                    self.assertGreater(o[x, y], 100,
                                       'inset leaks outside the outline at %d,%d' % (x, y))

        # A border must exist at the spike tips, i.e. the top of the inset
        # sits strictly below the top of the outline by at least the inset.
        self.assertGreaterEqual(inset.getbbox()[1] - outer.getbbox()[1], 14,
                                'no white border at the spike tips')

    def test_shape_is_stable_across_rebuilds(self, _geo):
        sp = Species.objects.create(common_name='Crab')
        s = Sticker.objects.create(species=sp, media=a_photo())
        first = s.resolved_shape
        self.assertIn(first, [slug for slug, _ in shapes.available()])
        self.assertEqual(first, Sticker.objects.get(pk=s.pk).resolved_shape)

    def test_explicit_shape_overrides_auto(self, _geo):
        sp = Species.objects.create(common_name='Crab')
        s = Sticker.objects.create(species=sp, media=a_photo(), shape='06-splat')
        self.assertEqual(s.resolved_shape, '06-splat')
        self.assertIn('06-splat', s.shape_mask_url)
        self.assertIn('06-splat', s.shape_svg_url)

    def test_gif_is_animated_and_served_whole(self, _geo):
        """A GIF must keep moving, so the card renders the original file."""
        buf = io.BytesIO()
        Image.new('RGB', (400, 300), (200, 40, 40)).save(buf, 'GIF')
        gif = SimpleUploadedFile('crab.gif', buf.getvalue(), content_type='image/gif')
        sp = Species.objects.create(common_name='Crab')
        s = Sticker.objects.create(species=sp, media=gif,
                                   status=Sticker.Status.PUBLISHED)
        self.assertTrue(s.is_gif)
        self.assertTrue(s.is_animated)
        self.assertFalse(s.is_video)
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn(s.media.url, body, 'the GIF itself should be on the sheet')

    def test_card_carries_the_shape_for_css_cropping(self, _geo):
        sp = Species.objects.create(common_name='Crab')
        s = Sticker.objects.create(species=sp, media=a_photo(),
                                   status=Sticker.Status.PUBLISHED,
                                   shape='06-splat')
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('--shape:', body)
        self.assertIn('--shape-mask:', body)
        self.assertIn('06-splat.mask.png', body)


class TemplateCommentTests(TestCase):
    """
    Django's `{# ... #}` is SINGLE-LINE only. Spread one over several lines and
    it is not a comment at all — the whole thing renders as visible page text,
    which is exactly what shipped to the live sheet once. Multi-line notes must
    use {% comment %}.
    """

    def test_no_multiline_hash_comments_in_templates(self):
        import glob
        offenders = []
        for path in glob.glob(os.path.join(
                os.path.dirname(__file__), 'templates', 'stickers', '*.html')):
            for n, line in enumerate(open(path).read().splitlines(), 1):
                if '{#' in line and '#}' not in line.split('{#', 1)[1]:
                    offenders.append('%s:%d' % (os.path.basename(path), n))
        self.assertEqual(offenders, [],
                         'multi-line {# #} renders as page text; use '
                         '{% comment %}: ' + ', '.join(offenders))

    def test_card_renders_no_prose_from_its_comment(self):
        species = Species.objects.create(common_name='Test crab')
        sticker = Sticker(pk=7, species=species, slug='test-crab-7')
        from django.template.loader import render_to_string
        out = render_to_string('stickers/_sticker_card.html', {'s': sticker})
        for leak in ('One sticker on the sheet', 'vinyl border', 'endcomment'):
            self.assertNotIn(leak, out)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class SvgApiTests(TestCase):
    """Serving a sticker as vector."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _published(self, **kw):
        species = Species.objects.create(common_name='Anemone')
        return Sticker.objects.create(species=species, media=a_photo(),
                                      status=Sticker.Status.PUBLISHED, **kw)

    def test_svg_endpoint_serves_svg(self, _geo):
        s = self._published(shape='06-splat')
        r = self.client.get('/api/stickers/%s/svg/' % s.slug)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'image/svg+xml')
        body = r.content.decode()
        self.assertTrue(body.lstrip().startswith('<svg'))
        self.assertIn('clipPath', body)
        self.assertIn('</svg>', body)

    def test_svg_uses_the_same_outline_as_the_png(self, _geo):
        """The vector and the raster must be cut with the identical path."""
        s = self._published(shape='06-splat')
        body = self.client.get('/api/stickers/%s/svg/' % s.slug).content.decode()
        self.assertIn(shapes.raw_path('06-splat'), body)

    def test_border_is_stroked_inside_the_clip(self, _geo):
        """
        The uniform border depends on the stroked paths sitting INSIDE the
        clip group — outside it, half the stroke would hang past the die-cut
        edge instead of being trimmed to a clean inset.
        """
        s = self._published(shape='07-classic-starburst')
        body = self.client.get('/api/stickers/%s/svg/' % s.slug).content.decode()
        group = body.split('<g clip-path=')[1].split('</g>')[0]
        self.assertIn('stroke="#ffffff"', group)
        self.assertIn('stroke="#141210"', group)

    def test_linked_svg_is_small_embedded_is_selfcontained(self, _geo):
        s = self._published()
        linked = self.client.get('/api/stickers/%s/svg/' % s.slug).content
        embedded = self.client.get('/api/stickers/%s/svg/?embed=1' % s.slug).content
        self.assertNotIn(b'data:image', linked)
        self.assertIn(b'data:image', embedded)
        self.assertGreater(len(embedded), len(linked))

    def test_download_flag_sets_attachment(self, _geo):
        s = self._published()
        r = self.client.get('/api/stickers/%s/svg/?download=1' % s.slug)
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('.svg', r['Content-Disposition'])

    def test_unpublished_sticker_has_no_svg(self, _geo):
        species = Species.objects.create(common_name='Secret')
        s = Sticker.objects.create(species=species, media=a_photo(),
                                   status=Sticker.Status.PENDING)
        self.assertEqual(
            self.client.get('/api/stickers/%s/svg/' % s.slug).status_code, 404)

    def test_list_advertises_the_svg_urls(self, _geo):
        self._published(shape='06-splat')
        row = self.client.get('/api/stickers/').json()['results'][0]
        self.assertIn('/svg/', row['svg'])
        self.assertIn('embed=1', row['svg_embedded'])
        self.assertEqual(row['shape'], '06-splat')
        self.assertIn('06-splat.svg', row['shape_svg'])

    def test_shapes_endpoint_lists_outlines(self, _geo):
        rows = self.client.get('/api/shapes/').json()
        self.assertGreaterEqual(len(rows), 10)
        first = rows[0]
        for key in ('slug', 'label', 'svg', 'mask_png', 'path'):
            self.assertIn(key, first)
        self.assertTrue(first['path'].startswith('M'))


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class SoftDeleteTests(TestCase):
    """
    Deleting a sticker must never destroy the upload. A submitted photo is
    the only copy — this exists because a blanket
    `Sticker.objects.all().delete()` during cleanup wiped a real submission
    and its file on 2026-09-22.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _sticker(self, **kw):
        species = kw.pop('species', None) or Species.objects.create(
            common_name='Anemone')
        return Sticker.objects.create(species=species, media=a_photo(),
                                      status=Sticker.Status.PUBLISHED, **kw)

    def test_instance_delete_is_soft_and_keeps_the_file(self, _geo):
        s = self._sticker()
        path = s.media.path
        s.delete()
        self.assertTrue(os.path.exists(path), 'the upload was destroyed')
        self.assertTrue(Sticker.all_objects.filter(pk=s.pk).exists())
        self.assertFalse(Sticker.objects.filter(pk=s.pk).exists())

    def test_queryset_delete_is_soft(self, _geo):
        """The exact call that caused the incident."""
        s = self._sticker()
        path = s.media.path
        Sticker.objects.all().delete()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(Sticker.all_objects.count(), 1)
        self.assertEqual(Sticker.objects.count(), 0)

    def test_deleted_sticker_leaves_the_sheet_and_the_api(self, _geo):
        s = self._sticker()
        self.assertContains(self.client.get(reverse('stickers:sheet')), 'Anemone')
        s.delete()
        self.assertNotContains(self.client.get(reverse('stickers:sheet')), 'Anemone')
        self.assertEqual(self.client.get('/api/stickers/').json()['count'], 0)
        self.assertEqual(
            self.client.get('/api/stickers/%s/svg/' % s.slug).status_code, 404)

    def test_restore_brings_it_back(self, _geo):
        s = self._sticker()
        s.delete()
        s.restore()
        self.assertFalse(Sticker.objects.get(pk=s.pk).is_deleted)
        self.assertContains(self.client.get(reverse('stickers:sheet')), 'Anemone')

    def test_counts_ignore_binned_stickers(self, _geo):
        """
        An annotation joins in SQL and does NOT go through the manager, so the
        deleted_at test must be written out by hand. Miss it and the chips and
        the species API count stickers that are in the bin.
        """
        species = Species.objects.create(common_name='Anemone')
        keep = self._sticker(species=species)
        binned = self._sticker(species=species)
        binned.delete()

        rows = self.client.get('/api/species/').json()['results']
        self.assertEqual(rows[0]['sticker_count'], 1)
        self.assertEqual(species.published_count, 1)

        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('1 sticker,', body)
        self.assertEqual(keep.species_id, species.pk)

    def test_hard_delete_is_available_but_explicit(self, _geo):
        s = self._sticker()
        path = s.media.path
        s.hard_delete()
        self.assertFalse(Sticker.all_objects.filter(pk=s.pk).exists())
        self.assertTrue(os.path.exists(path),
                        'hard_delete should not unlink the file unless asked')

    def test_hard_delete_can_remove_the_file_when_asked(self, _geo):
        s = self._sticker()
        path = s.media.path
        s.hard_delete(delete_file=True)
        self.assertFalse(os.path.exists(path))

    def test_admin_restore_works_from_the_default_view(self, _geo):
        """
        BinFilter hides binned rows from the default changelist, so the action
        must resolve its selection from the POST instead of from the filtered
        queryset — otherwise restoring silently does nothing.
        """
        from django.contrib.admin import helpers as admin_helpers
        from django.contrib.auth.models import User
        User.objects.create_superuser('mod', 'm@example.com', 'pw')
        self.client.force_login(User.objects.get(username='mod'))

        s = self._sticker()
        s.delete()
        self.client.post('/admin/stickers/sticker/', {
            'action': 'restore',
            admin_helpers.ACTION_CHECKBOX_NAME: [str(s.pk)],
        }, follow=True)
        self.assertFalse(Sticker.objects.get(pk=s.pk).is_deleted)

    def test_admin_delete_selected_is_soft(self, _geo):
        from django.contrib.admin import helpers as admin_helpers
        from django.contrib.auth.models import User
        User.objects.create_superuser('mod2', 'm2@example.com', 'pw')
        self.client.force_login(User.objects.get(username='mod2'))

        s = self._sticker()
        path = s.media.path
        self.client.post('/admin/stickers/sticker/', {
            'action': 'delete_selected',
            admin_helpers.ACTION_CHECKBOX_NAME: [str(s.pk)],
            'post': 'yes',
        }, follow=True)
        self.assertTrue(os.path.exists(path), 'admin delete destroyed the file')
        self.assertTrue(Sticker.all_objects.filter(pk=s.pk).exists())
        self.assertTrue(Sticker.all_objects.get(pk=s.pk).is_deleted)

    def test_species_fk_still_resolves_for_a_binned_sticker(self, _geo):
        """base_manager_name must expose every row, or the FK looks dangling."""
        s = self._sticker()
        s.delete()
        fetched = Sticker.all_objects.get(pk=s.pk)
        self.assertEqual(fetched.species.common_name, 'Anemone')
