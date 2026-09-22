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
from django.conf import settings as django_settings
from django.core.files.storage import FileSystemStorage, Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from . import shapes, svg
from .models import Species, Sticker

MEDIA = tempfile.mkdtemp(prefix='stickertest-')


def a_photo(name='crab.jpg', size=(1600, 1200)):
    buf = io.BytesIO()
    Image.new('RGB', size, (31, 120, 140)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


def a_varied_photo(name='varied.jpg', size=(1600, 1200)):
    """
    A photo whose regions differ, so two different crops of it produce
    different bytes.

    `a_photo` is a flat colour, which is fine for "was a file built" but
    useless for "did re-framing change the picture" — every crop of a uniform
    image is identical, and such a test passes or fails for the wrong reason.
    """
    img = Image.new('RGB', size, (20, 30, 40))
    draw = ImageDraw.Draw(img)
    w, h = size
    for i in range(12):
        for j in range(9):
            if (i + j) % 2:
                draw.rectangle([i * w // 12, j * h // 9,
                                (i + 1) * w // 12, (j + 1) * h // 9],
                               fill=(30 + i * 18, 200 - j * 20, 60 + j * 22))
    draw.ellipse([w // 3, h // 3, 2 * w // 3, 2 * h // 3], fill=(255, 209, 26))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=92)
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
        from django.core.files.storage import default_storage
        s = self._sticker()
        for suffix in ('.sticker.png', '.thumb.jpg', '.lowres.jpg'):
            self.assertTrue(s._derivative_exists(suffix),
                            '%s was not built' % suffix)
        with default_storage.open(s._derivative_name('.sticker.png'), 'rb') as fh:
            png = Image.open(fh)
            png.load()
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
        self.assertEqual(body.count('class="ss-sticker"'), 1,
                         'the binned sticker is still being rendered')
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


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class FramingTests(TestCase):
    """Choosing a shape and positioning it over the media."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_crop_follows_the_focal_point(self, _geo):
        """
        focal_crop must take the square AROUND the focal point, clamped to the
        image. framer.js duplicates this rule; if this changes, change it too.
        """
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (1000, 500))
        # zoom 1 on a 1000x500 gives a 500px square; focal 0.5 centres it.
        self.assertEqual(focal_crop(img, (0.5, 0.5, 1.0)).size, (500, 500))
        # hard left should clamp to x=0, not run off the edge
        left = focal_crop(img, (0.0, 0.5, 1.0))
        self.assertEqual(left.size, (500, 500))
        # zoom 2 halves the square
        self.assertEqual(focal_crop(img, (0.5, 0.5, 2.0)).size, (250, 250))

    def test_crop_is_always_square(self, _geo):
        """Rounding each edge separately used to yield e.g. 402x401."""
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (1177, 883))
        for zoom in (1.0, 1.7, 2.2, 3.3, 4.0):
            out = focal_crop(img, (0.3, 0.62, zoom))
            self.assertEqual(out.size[0], out.size[1],
                             'crop not square at zoom %s: %s' % (zoom, out.size))

    def test_crop_is_clamped_inside_the_image(self, _geo):
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (800, 600))
        for fx, fy in ((0.0, 0.0), (1.0, 1.0), (-5, 5)):
            out = focal_crop(img, (fx, fy, 1.0))
            self.assertEqual(out.size, (600, 600), 'crop left the image bounds')

    def test_zoom_is_clamped(self, _geo):
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (400, 400))
        # absurd zoom must not produce a zero-size crop
        self.assertGreater(min(focal_crop(img, (0.5, 0.5, 99)).size), 0)
        # a square image cannot zoom out: there is nothing beyond the edges
        self.assertEqual(focal_crop(img, (0.5, 0.5, 0.1)).size, (400, 400))

    def test_zooming_out_grows_the_square_past_the_short_side(self, _geo):
        """Below zoom 1 the square exceeds min(w, h) and the rest is padded."""
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (1600, 1200), (31, 120, 140))
        self.assertEqual(focal_crop(img, (0.5, 0.5, 1.0)).size, (1200, 1200))
        self.assertEqual(focal_crop(img, (0.5, 0.5, 0.85)).size, (1412, 1412))

    def test_zoom_out_stops_at_the_whole_image(self, _geo):
        """You cannot pull back into an endless white field."""
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (1600, 1200), (31, 120, 140))
        for zoom in (0.75, 0.5, 0.2):
            self.assertEqual(focal_crop(img, (0.5, 0.5, zoom)).size, (1600, 1600))

    def test_zoomed_out_padding_is_white_and_the_picture_survives(self, _geo):
        from stickers.imaging import focal_crop, PAD
        img = Image.new('RGB', (1600, 1200), (31, 120, 140))
        out = focal_crop(img, (0.5, 0.5, 0.75))     # whole frame, padded
        self.assertEqual(out.size, (1600, 1600))
        self.assertEqual(out.getpixel((800, 5)), PAD, 'top band should be padding')
        self.assertEqual(out.getpixel((800, 800)), (31, 120, 140),
                         'the picture itself should still be there')

    def test_zoomed_out_crop_is_still_square(self, _geo):
        from stickers.imaging import focal_crop
        img = Image.new('RGB', (1177, 883))
        for zoom in (0.76, 0.9, 0.99):
            out = focal_crop(img, (0.3, 0.62, zoom))
            self.assertEqual(out.size[0], out.size[1],
                             'not square at zoom %s: %s' % (zoom, out.size))

    def test_form_accepts_a_zoomed_out_framing(self, _geo):
        self.client.post(reverse('stickers:submit'), {
            'species_name': 'Anemone', 'media': a_photo(),
            'zoom': '0.7',
        })
        self.assertAlmostEqual(Sticker.objects.get().zoom, 0.7)

    def test_form_accepts_a_shape_and_framing(self, _geo):
        r = self.client.post(reverse('stickers:submit'), {
            'species_name': 'Anemone', 'media': a_photo(),
            'shape': '06-splat', 'focal_x': '0.25', 'focal_y': '0.75',
            'zoom': '2.5',
        })
        self.assertRedirects(r, reverse('stickers:submitted'))
        s = Sticker.objects.get()
        self.assertEqual(s.shape, '06-splat')
        self.assertAlmostEqual(s.focal_x, 0.25)
        self.assertAlmostEqual(s.focal_y, 0.75)
        self.assertAlmostEqual(s.zoom, 2.5)

    def test_form_rejects_an_unknown_shape(self, _geo):
        r = self.client.post(reverse('stickers:submit'), {
            'species_name': 'Anemone', 'media': a_photo(),
            'shape': '../../etc/passwd',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Sticker.objects.exists())

    def test_form_clamps_silly_framing(self, _geo):
        self.client.post(reverse('stickers:submit'), {
            'species_name': 'Anemone', 'media': a_photo(),
            'focal_x': '9', 'focal_y': '-3', 'zoom': '900',
        })
        s = Sticker.objects.get()
        self.assertEqual(s.focal_x, 1.0)
        self.assertEqual(s.focal_y, 0.0)
        self.assertEqual(s.zoom, 4.0)

    def test_absurd_zoom_out_is_clamped_not_rejected(self, _geo):
        from stickers import imaging
        self.client.post(reverse('stickers:submit'), {
            'species_name': 'Anemone', 'media': a_photo(), 'zoom': '-5',
        })
        self.assertEqual(Sticker.objects.get().zoom, imaging.MIN_ZOOM)

    def test_submit_page_offers_every_shape(self, _geo):
        body = self.client.get(reverse('stickers:submit')).content.decode()
        for slug, _label in shapes.available():
            self.assertIn('data-shape="%s"' % slug, body)
        self.assertIn('data-framer', body)
        self.assertIn('surprise me', body)

    def test_detail_page_has_no_map_or_download(self, _geo):
        species = Species.objects.create(common_name='Anemone')
        s = Sticker.objects.create(species=species, media=a_photo(),
                                   status=Sticker.Status.PUBLISHED,
                                   location='Pillar Point')
        body = self.client.get(s.get_absolute_url()).content.decode()
        self.assertNotIn('openstreetmap', body.lower())
        self.assertNotIn('download the sticker', body.lower())
        self.assertIn('dipsticker sheet', body)

    def test_sticker_pages_share_the_site_navbar(self, _geo):
        """
        The sheet is a page of dipstick.earth now, so it gets the same navbar
        as everything else. (An earlier version of this test asserted the wiki
        links were absent — that was right for the standalone sticker site and
        is wrong for the merged one.)
        """
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        nav = body.split('<nav')[1].split('</nav>')[0]
        self.assertIn('id="mainNav"', nav)
        self.assertIn('>dipstickers<', nav)
        self.assertIn('Assembly Guide', nav)
        # workshops.dipstick.earth is still its own site and is not linked here
        self.assertNotIn('workshops.dipstick.earth', nav)

    def test_sheet_says_dipstickers(self, _geo):
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('dipstickers', body)
        self.assertIn('90s stickers of animals filmed with dipsticks',
                      body)


class CloudflareRealIPTests(TestCase):
    """
    Behind Cloudflare every request arrives from an edge address, so anything
    keyed on REMOTE_ADDR — the submit throttle above all — collapses into one
    bucket for the whole internet unless CF-Connecting-IP is honoured.
    """

    def _remote_addr_seen_by_the_view(self, **meta):
        from stickers.middleware import CloudflareRealIPMiddleware
        seen = {}

        def view(request):
            seen['addr'] = request.META.get('REMOTE_ADDR')
            return 'ok'

        from django.test import RequestFactory
        request = RequestFactory().get('/', **meta)
        CloudflareRealIPMiddleware(view)(request)
        return seen['addr']

    def test_header_is_honoured_from_a_cloudflare_address(self):
        addr = self._remote_addr_seen_by_the_view(
            REMOTE_ADDR='162.158.1.1',            # inside 162.158.0.0/15
            HTTP_CF_CONNECTING_IP='71.255.58.246')
        self.assertEqual(addr, '71.255.58.246')

    def test_header_is_ignored_from_anywhere_else(self):
        """
        The origin is still reachable directly, so an unfiltered header would
        let anyone choose their own throttle bucket.
        """
        addr = self._remote_addr_seen_by_the_view(
            REMOTE_ADDR='203.0.113.9',            # not Cloudflare
            HTTP_CF_CONNECTING_IP='71.255.58.246')
        self.assertEqual(addr, '203.0.113.9')

    def test_malformed_header_does_not_replace_the_address(self):
        addr = self._remote_addr_seen_by_the_view(
            REMOTE_ADDR='162.158.1.1',
            HTTP_CF_CONNECTING_IP='not-an-ip')
        self.assertEqual(addr, '162.158.1.1')

    def test_no_header_is_a_no_op(self):
        self.assertEqual(
            self._remote_addr_seen_by_the_view(REMOTE_ADDR='162.158.1.1'),
            '162.158.1.1')


class MergedSiteTests(TestCase):
    """The static site and the sticker sheet are one Django site now."""

    def test_navbar_has_the_whole_site(self):
        nav = self.client.get(reverse('pages:index')).content.decode()
        nav = nav.split('<nav')[1].split('</nav>')[0]
        for label in ('Assembly Guide', 'DIY', 'Community',
                      'dipstickers', 'Contact us'):
            self.assertIn('>%s<' % label, nav, '%s missing from the navbar' % label)
        self.assertIn('Assembly_Guide', nav)
        self.assertIn('Open-Source_Design_page', nav)
        self.assertIn('discord.gg', nav)
        self.assertNotIn('>Intro<', nav)

        # The three links that leave the site open in a new tab, and carry
        # rel=noopener so the opened page cannot reach back via window.opener.
        import re as _re
        for href in ('Assembly_Guide', 'Open-Source_Design_page', 'discord.gg'):
            anchor = _re.search(r'<a[^>]*%s[^>]*>' % href, nav).group(0)
            self.assertIn('target="_blank"', anchor, '%s not new-tab' % href)
            self.assertIn('noopener', anchor, '%s missing rel=noopener' % href)

        # Internal links stay in the tab.
        internal = _re.search(r'<a[^>]*href="%s"[^>]*>' % reverse('stickers:sheet'),
                              nav).group(0)
        self.assertNotIn('target="_blank"', internal)
        # The home page is still reachable — the brand logo links to it.
        self.assertIn('navbar-brand', nav)
        self.assertIn('href="%s"' % reverse('pages:index'), nav)

    def test_marketing_pages_render(self):
        for name in ('pages:index', 'pages:contacts', 'pages:kickstarter'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, 'id="mainNav"')

    def test_legacy_html_urls_redirect(self):
        for old, new in (('/index.html', '/'),
                         ('/contacts.html', '/contacts/'),
                         ('/kickstarter/index.html', '/kickstarter/')):
            r = self.client.get(old)
            self.assertEqual(r.status_code, 301, old)
            self.assertEqual(r['Location'], new)

    def test_the_sheet_lives_at_dipstickers(self):
        self.assertEqual(reverse('stickers:sheet'), '/dipstickers/')
        self.assertEqual(self.client.get('/dipstickers/').status_code, 200)

    def test_the_old_gallery_urls_still_resolve(self):
        """
        The sheet has moved twice — its own host, then /gallery/. Links people
        already shared have to keep working, including deep ones.
        """
        for old, new in (('/gallery/', '/dipstickers/'),
                         ('/gallery/submit/', '/dipstickers/submit/'),
                         ('/gallery/sticker/foo-1/', '/dipstickers/sticker/foo-1/')):
            r = self.client.get(old)
            self.assertEqual(r.status_code, 301, old)
            self.assertEqual(r['Location'], new)

    def test_one_navbar_for_every_page(self):
        """The duplication that prompted the merge must not creep back."""
        import glob, os
        roots = ['pages/templates', 'stickers/templates', 'templates']
        navs = []
        for root in roots:
            base = os.path.join(os.path.dirname(os.path.dirname(__file__)), root)
            for path in glob.glob(base + '/**/*.html', recursive=True):
                if '<nav' in open(path).read():
                    navs.append(os.path.relpath(path, base))
        self.assertEqual(len(navs), 1,
                         'navbar markup should exist once, found in: %s' % navs)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class HiddenFiltersTests(TestCase):
    """
    Search and the group chips are hidden for now
    (STICKER_SHEET_SHOW_FILTERS). Hidden means the UI is gone — the filtering
    itself must keep working from the URL and the API, so turning it back on
    is one setting and no code.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _published(self, name='Anemone', group='invertebrate'):
        species = Species.objects.create(common_name=name, group=group)
        return Sticker.objects.create(species=species, media=a_photo(),
                                      status=Sticker.Status.PUBLISHED)

    @override_settings(STICKER_SHEET_SHOW_FILTERS=False)
    def test_sheet_shows_no_search_or_chips(self, _geo):
        self._published()
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertNotIn('ss-filter', body)
        self.assertNotIn('ss-chip', body)
        self.assertIn('dipstickers', body)          # the page still renders

    @override_settings(STICKER_SHEET_SHOW_FILTERS=False)
    def test_detail_hides_the_group_row(self, _geo):
        s = self._published()
        body = self.client.get(s.get_absolute_url()).content.decode()
        self.assertNotIn('>Group<', body)

    @override_settings(STICKER_SHEET_SHOW_FILTERS=False)
    def test_facts_list_is_absent_when_it_would_be_empty(self, _geo):
        """Group was the only always-present row; without it the bordered
        box would otherwise render empty."""
        s = self._published()
        self.assertFalse(s.wildlife_investigator or s.location or s.captured_at)
        body = self.client.get(s.get_absolute_url()).content.decode()
        self.assertNotIn('ss-facts', body)

    @override_settings(STICKER_SHEET_SHOW_FILTERS=False)
    def test_facts_list_still_renders_when_there_is_something_to_say(self, _geo):
        species = Species.objects.create(common_name='Anemone')
        s = Sticker.objects.create(species=species, media=a_photo(),
                                   status=Sticker.Status.PUBLISHED,
                                   wildlife_investigator='Ada L.')
        body = self.client.get(s.get_absolute_url()).content.decode()
        self.assertIn('ss-facts', body)
        self.assertIn('Ada L.', body)

    @override_settings(STICKER_SHEET_SHOW_FILTERS=False)
    def test_filtering_still_works_from_the_url(self, _geo):
        self._published('Anemone', 'invertebrate')
        self._published('Blenny', 'fish')
        body = self.client.get(reverse('stickers:sheet'), {'q': 'Blenny'}).content.decode()
        self.assertIn('Blenny', body)
        self.assertNotIn('Anemone', body)
        body = self.client.get(reverse('stickers:sheet'), {'group': 'fish'}).content.decode()
        self.assertIn('Blenny', body)
        self.assertNotIn('Anemone', body)

    @override_settings(STICKER_SHEET_SHOW_FILTERS=True)
    def test_turning_the_flag_back_on_restores_both(self, _geo):
        self._published()
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('ss-filter', body)
        self.assertIn('ss-chip', body)
        s = Sticker.objects.first()
        self.assertIn('>Group<', self.client.get(s.get_absolute_url()).content.decode())


class PathlessStorage(Storage):
    """
    A stand-in for S3Storage: stores files locally but refuses to hand out a
    filesystem path, exactly as S3Storage does.

    `.path` is the thing the derivative pipeline used to depend on, so running
    the whole pipeline against this proves the storage refactor holds with no
    network and no credentials — and it fails loudly if anyone reintroduces a
    `.path` call.

    It delegates to a private FileSystemStorage rather than subclassing one:
    FileSystemStorage.save() calls self.path() internally, so a subclass that
    raises would break saving itself rather than the caller.
    """

    def __init__(self, location=None, **kwargs):
        self._inner = FileSystemStorage(
            location=location or django_settings.MEDIA_ROOT)

    def path(self, name):
        raise NotImplementedError("This backend doesn't support absolute paths.")

    def _open(self, name, mode='rb'):
        return self._inner._open(name, mode)

    def _save(self, name, content):
        return self._inner._save(name, content)

    def exists(self, name):
        return self._inner.exists(name)

    def delete(self, name):
        return self._inner.delete(name)

    def url(self, name):
        return self._inner.url(name)

    def size(self, name):
        return self._inner.size(name)

    def get_available_name(self, name, max_length=None):
        return self._inner.get_available_name(name, max_length)


PATHLESS_MEDIA = tempfile.mkdtemp(prefix='stickerpathless-')


@override_settings(
    MEDIA_ROOT=PATHLESS_MEDIA,
    STORAGES={
        'default': {'BACKEND': 'stickers.tests.PathlessStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
@mock.patch('stickers.models.geocode', return_value=None)
class RemoteStorageTests(TestCase):
    """The pipeline must not touch the filesystem directly anywhere."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(PATHLESS_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _sticker(self, media=None, **kw):
        species = Species.objects.create(common_name='Anemone')
        return Sticker.objects.create(species=species, media=media or a_photo(),
                                      status=Sticker.Status.PUBLISHED, **kw)

    def test_derivatives_build_without_any_local_path(self, _geo):
        from django.core.files.storage import default_storage
        s = self._sticker(shape='06-splat')
        for suffix in ('.sticker.png', '.thumb.jpg', '.lowres.jpg'):
            self.assertTrue(s._derivative_exists(suffix),
                            '%s was not built on a path-less storage' % suffix)
            self.assertTrue(
                default_storage.exists(s._derivative_name(suffix)))

    def test_the_die_cut_is_still_a_real_sticker(self, _geo):
        from django.core.files.storage import default_storage
        s = self._sticker(shape='06-splat')
        with default_storage.open(s._derivative_name('.sticker.png'), 'rb') as fh:
            png = Image.open(fh)
            png.load()
        self.assertEqual(png.mode, 'RGBA')
        self.assertEqual(png.getpixel((2, 2))[3], 0, 'corner should be cut away')
        self.assertEqual(png.getpixel((512, 512))[3], 255, 'middle should be opaque')

    def test_urls_resolve(self, _geo):
        s = self._sticker()
        for url in (s.thumb_url, s.lowres_url, s.sticker_url):
            self.assertTrue(url, 'a derivative URL came back empty')

    def test_the_page_renders(self, _geo):
        s = self._sticker()
        self.assertContains(self.client.get(reverse('stickers:sheet')), 'Anemone')
        self.assertEqual(self.client.get(s.get_absolute_url()).status_code, 200)

    def test_embedded_svg_reads_through_storage(self, _geo):
        s = self._sticker(shape='06-splat')
        body = self.client.get('/api/stickers/%s/svg/?embed=1' % s.slug).content
        self.assertIn(b'data:image', body)

    def test_lazy_rebuild_works_remotely(self, _geo):
        from django.core.files.storage import default_storage
        s = self._sticker()
        name = s._derivative_name('.thumb.jpg')
        default_storage.delete(name)
        self.assertFalse(s._derivative_exists('.thumb.jpg'))
        self.assertTrue(s.thumb_url, 'lazy rebuild failed on remote storage')
        self.assertTrue(s._derivative_exists('.thumb.jpg'))

    def test_hard_delete_removes_from_storage(self, _geo):
        from django.core.files.storage import default_storage
        s = self._sticker()
        media_name = s.media.name
        thumb_name = s._derivative_name('.thumb.jpg')
        s.hard_delete(delete_file=True)
        self.assertFalse(default_storage.exists(media_name))
        self.assertFalse(default_storage.exists(thumb_name))

    def test_publish_overwrites_rather_than_suffixing(self, _geo):
        """
        storage.save() suffixes on collision (foo_a8Kd2.jpg). A rebuild must
        land on the SAME key or the model points at a name that no longer
        exists.
        """
        s = self._sticker()
        name = s._derivative_name('.thumb.jpg')
        s.build_derivatives()
        s.build_derivatives()
        self.assertEqual(s._derivative_name('.thumb.jpg'), name)
        self.assertTrue(s._derivative_exists('.thumb.jpg'))


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class ReframingTests(TestCase):
    """
    The framing a person chose is kept on the sticker so it can be changed
    later — and changing it has to actually re-cut the image, not just update
    the numbers.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _sticker(self, **kw):
        species = Species.objects.create(common_name='Anemone')
        # Varied, not flat: a re-crop of a flat image is byte-identical, so
        # these assertions would pass no matter what the code did.
        return Sticker.objects.create(species=species, media=a_varied_photo(),
                                      status=Sticker.Status.PUBLISHED, **kw)

    def _sticker_bytes(self, s):
        from django.core.files.storage import default_storage
        with default_storage.open(s._derivative_name('.sticker.png'), 'rb') as fh:
            return fh.read()

    def test_framing_survives_a_round_trip(self, _geo):
        s = self._sticker(shape='06-splat', focal_x=0.25, focal_y=0.7, zoom=2.2)
        fresh = Sticker.objects.get(pk=s.pk)
        self.assertEqual(fresh.shape, '06-splat')
        self.assertAlmostEqual(fresh.focal_x, 0.25)
        self.assertAlmostEqual(fresh.focal_y, 0.7)
        self.assertAlmostEqual(fresh.zoom, 2.2)
        self.assertEqual(fresh.framing, (0.25, 0.7, 2.2))

    def test_changing_the_zoom_recuts_the_sticker(self, _geo):
        s = self._sticker(zoom=1.0)
        before = self._sticker_bytes(s)
        s.zoom = 2.5
        s.save()
        self.assertNotEqual(before, self._sticker_bytes(s),
                            'the PNG still shows the old crop')

    def test_changing_the_shape_recuts_the_sticker(self, _geo):
        s = self._sticker(shape='01-soft-rectangle')
        before = self._sticker_bytes(s)
        s.shape = '07-classic-starburst'
        s.save()
        self.assertNotEqual(before, self._sticker_bytes(s))

    def test_panning_recuts_the_sticker(self, _geo):
        s = self._sticker(zoom=2.0, focal_x=0.5, focal_y=0.5)
        before = self._sticker_bytes(s)
        s.focal_x, s.focal_y = 0.2, 0.8
        s.save()
        self.assertNotEqual(before, self._sticker_bytes(s))

    def test_an_unrelated_edit_does_not_rebuild(self, _geo):
        """Rebuilding runs Pillow synchronously; don't do it for a caption."""
        s = self._sticker()
        before = self._sticker_bytes(s)
        s.caption = 'sidestepping under a rock'
        s.save()
        self.assertEqual(before, self._sticker_bytes(s))

    def test_reframing_is_editable_in_the_admin(self, _geo):
        from django.contrib.auth.models import User
        User.objects.create_superuser('mod3', 'm3@example.com', 'pw')
        self.client.force_login(User.objects.get(username='mod3'))
        s = self._sticker()
        body = self.client.get(
            '/admin/stickers/sticker/%d/change/' % s.pk).content.decode()
        for field in ('name="shape"', 'name="focal_x"', 'name="focal_y"',
                      'name="zoom"'):
            self.assertIn(field, body, '%s missing from the admin form' % field)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class ReviewPageTests(TestCase):
    """The staff queue, and re-cutting a sticker from it."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_superuser('mod4', 'm4@x.com', 'pw')

    def _sticker(self, status=Sticker.Status.PENDING, **kw):
        species = Species.objects.create(
            common_name=kw.pop('name', 'Anemone %d' % Sticker.all_objects.count()))
        return Sticker.objects.create(species=species, media=a_varied_photo(),
                                      status=status, **kw)

    def _bytes(self, s):
        from django.core.files.storage import default_storage
        with default_storage.open(s._derivative_name('.sticker.png'), 'rb') as fh:
            return fh.read()

    # --- access ---------------------------------------------------------
    def test_review_is_staff_only(self, _geo):
        for url in (reverse('stickers:review'),):
            r = self.client.get(url)
            self.assertIn(r.status_code, (302, 403), 'anonymous got in')
            self.assertNotIn(b'moderation', r.content.lower())

    def test_reframe_is_staff_only(self, _geo):
        s = self._sticker()
        r = self.client.get(reverse('stickers:reframe', args=[s.slug]))
        self.assertIn(r.status_code, (302, 403))

    def test_staff_can_open_both(self, _geo):
        s = self._sticker()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('stickers:review')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('stickers:reframe', args=[s.slug])).status_code, 200)

    # --- the queue ------------------------------------------------------
    def test_queue_shows_pending_by_default(self, _geo):
        pending = self._sticker(name='Waiting thing')
        published = self._sticker(Sticker.Status.PUBLISHED, name='Live thing')
        self.client.force_login(self.staff)
        body = self.client.get(reverse('stickers:review')).content.decode()
        self.assertIn('Waiting thing', body)
        self.assertNotIn('Live thing', body)

    def test_publish_from_the_queue(self, _geo):
        s = self._sticker()
        self.client.force_login(self.staff)
        self.client.post(reverse('stickers:review'),
                         {'pk': s.pk, 'action': 'publish'}, follow=True)
        self.assertEqual(Sticker.objects.get(pk=s.pk).status,
                         Sticker.Status.PUBLISHED)

    def test_bin_from_the_queue_is_soft(self, _geo):
        """The upload is the only copy — binning must not destroy it."""
        from django.core.files.storage import default_storage
        s = self._sticker()
        name = s.media.name
        self.client.force_login(self.staff)
        self.client.post(reverse('stickers:review'),
                         {'pk': s.pk, 'action': 'bin'}, follow=True)
        self.assertTrue(Sticker.all_objects.get(pk=s.pk).is_deleted)
        self.assertTrue(default_storage.exists(name), 'binning deleted the file')

    def test_bin_tab_lists_and_restores(self, _geo):
        s = self._sticker()
        s.delete()
        self.client.force_login(self.staff)
        body = self.client.get(reverse('stickers:review'), {'show': 'bin'}).content.decode()
        self.assertIn(s.species.common_name, body)
        self.client.post(reverse('stickers:review'),
                         {'pk': s.pk, 'action': 'restore'}, follow=True)
        self.assertFalse(Sticker.all_objects.get(pk=s.pk).is_deleted)

    # --- re-framing -----------------------------------------------------
    def test_reframe_recuts_the_sticker(self, _geo):
        s = self._sticker(shape='01-soft-rectangle', zoom=1.0)
        before = self._bytes(s)
        self.client.force_login(self.staff)
        self.client.post(reverse('stickers:reframe', args=[s.slug]), {
            'shape': '07-classic-starburst',
            'focal_x': '0.3', 'focal_y': '0.7', 'zoom': '2.0',
        }, follow=True)
        s.refresh_from_db()
        self.assertEqual(s.shape, '07-classic-starburst')
        self.assertAlmostEqual(s.zoom, 2.0)
        self.assertNotEqual(before, self._bytes(s), 'the PNG was not re-cut')

    def test_reframe_loads_the_stored_framing(self, _geo):
        s = self._sticker(shape='06-splat', focal_x=0.25, focal_y=0.75, zoom=2.5)
        self.client.force_login(self.staff)
        body = self.client.get(reverse('stickers:reframe', args=[s.slug])).content.decode()
        self.assertIn('value="0.25"', body)
        self.assertIn('value="2.5"', body)
        self.assertIn('data-existing-url', body)

    def test_reframe_cannot_change_status_or_credit(self, _geo):
        """A re-frame is only a crop; it must not publish or rewrite people."""
        s = self._sticker(wildlife_investigator='Ada L.')
        self.client.force_login(self.staff)
        self.client.post(reverse('stickers:reframe', args=[s.slug]), {
            'shape': '06-splat', 'focal_x': '0.5', 'focal_y': '0.5', 'zoom': '1',
            'status': 'published', 'wildlife_investigator': 'Someone Else',
        }, follow=True)
        s.refresh_from_db()
        self.assertEqual(s.status, Sticker.Status.PENDING)
        self.assertEqual(s.wildlife_investigator, 'Ada L.')

    def test_save_and_publish_does_both(self, _geo):
        s = self._sticker()
        self.client.force_login(self.staff)
        self.client.post(reverse('stickers:reframe', args=[s.slug]), {
            'shape': '06-splat', 'focal_x': '0.5', 'focal_y': '0.5',
            'zoom': '1.5', 'and_publish': '1',
        }, follow=True)
        s.refresh_from_db()
        self.assertEqual(s.status, Sticker.Status.PUBLISHED)
        self.assertEqual(s.shape, '06-splat')

    def test_review_is_not_in_the_navbar_for_anyone(self, _geo):
        """
        Staff chrome does not belong on the public site. It used to be a nav
        item, which meant the home page rendered differently depending on who
        was looking at it.
        """
        for page in (reverse('pages:index'), reverse('stickers:sheet')):
            body = self.client.get(page).content.decode()
            self.assertNotIn(reverse('stickers:review'), body)
        self.client.force_login(self.staff)
        for page in (reverse('pages:index'), reverse('stickers:sheet')):
            nav = self.client.get(page).content.decode().split('</nav>')[0]
            self.assertNotIn(reverse('stickers:review'), nav,
                             'staff link leaked back into the navbar')

    def test_admin_changelist_links_to_the_review_queue(self, _geo):
        """It still has to be reachable — from the admin, where staff are."""
        self.client.force_login(self.staff)
        body = self.client.get('/admin/stickers/sticker/').content.decode()
        self.assertIn(reverse('stickers:review'), body)


class NavStylesheetTests(TestCase):
    """
    The navbar is one component on one site now, so its CSS lives in one
    place. It used to be duplicated into sheet.css from before the merge,
    which meant a nav change made there silently did nothing on the marketing
    pages — sheet.css only loads on the gallery.
    """

    def _css(self, name):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(base, name)).read()

    def test_navbar_css_is_not_duplicated(self):
        sheet = self._css('stickers/static/stickers/css/sheet.css')
        self.assertNotIn('#mainNav', sheet,
                         'navbar CSS is back in the gallery-only stylesheet')

    def test_navbar_css_is_in_the_site_wide_stylesheet(self):
        site = self._css('pages/static/assets/css/style-sticker.css')
        self.assertIn('#mainNav', site)
        # Vertical centring: the brand is 62px and the links ~28px, so
        # without this they sit against the top of the row.
        self.assertIn('#mainNav .nav-link { display: flex; align-items: center;',
                      site, 'the vertical centring rules are missing')
        # Horizontal centring is Bootstrap's .mx-auto, in flow. Absolute
        # positioning was tried and removed: out of flow, the list could run
        # under the CTA.
        self.assertNotIn('translate(-50%, -50%)', site,
                         'the nav list is out of flow again and can overlap the CTA')

    def test_every_page_loads_the_stylesheet_that_styles_the_nav(self):
        for name in ('pages:index', 'pages:contacts', 'stickers:sheet'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertIn('assets/css/style-sticker', body,
                          '%s does not load the navbar stylesheet' % name)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class LiveMediaFramingTests(TestCase):
    """
    A photo reaches the sheet already cropped, as a thumbnail. A video or GIF
    is served whole and cropped by the browser — and `object-fit: cover` is a
    centred crop at zoom 1, not the framing someone chose. That made a
    zoomed-out clip appear far closer in on the sheet than in its own cut PNG.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _sticker(self, **kw):
        species = Species.objects.create(common_name='Anemone')
        return Sticker.objects.create(species=species, media=a_varied_photo(),
                                      status=Sticker.Status.PUBLISHED, **kw)

    def test_dimensions_are_recorded(self, _geo):
        s = self._sticker()
        s.refresh_from_db()
        self.assertEqual((s.media_width, s.media_height), (1600, 1200))

    def test_live_crop_matches_focal_crop(self, _geo):
        """The CSS box and the cut must come from the same rule."""
        from stickers.imaging import focal_crop
        s = self._sticker(focal_x=0.3, focal_y=0.7, zoom=1.8)
        s.refresh_from_db()
        cw, ch, cl, ct = s.live_crop

        w, h = s.media_width, s.media_height
        box = focal_crop(Image.new('RGB', (w, h)), s.framing)
        side = box.size[0]
        # focal_crop rounds `side` to a whole pixel; live_crop keeps the float
        # because CSS percentages have no such constraint. Sub-pixel drift is
        # expected — anything bigger means the two rules have diverged.
        self.assertAlmostEqual(cw, w / side * 100, delta=0.5)
        self.assertAlmostEqual(ch, h / side * 100, delta=0.5)

    def test_zoomed_out_live_crop_is_not_a_cover_crop(self, _geo):
        """The regression itself: cover would be 133%, the framing is less."""
        s = self._sticker(zoom=0.8)
        s.refresh_from_db()
        cover = max(s.media_width, s.media_height) / min(s.media_width, s.media_height) * 100
        self.assertLess(s.live_crop[0], cover,
                        'zoomed-out media is still rendering as a cover crop')

    def test_card_emits_the_crop_for_a_gif(self, _geo):
        buf = io.BytesIO()
        Image.new('RGB', (800, 400), (200, 40, 40)).save(buf, 'GIF')
        gif = SimpleUploadedFile('c.gif', buf.getvalue(), content_type='image/gif')
        species = Species.objects.create(common_name='Crab')
        Sticker.objects.create(species=species, media=gif, zoom=1.2,
                               status=Sticker.Status.PUBLISHED)
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('--cw:', body)
        self.assertIn('ss-sticker__media--live', body)

    def test_photos_do_not_need_the_css_crop(self, _geo):
        """They are served pre-cropped; a second crop would double up."""
        self._sticker()
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        img = [l for l in body.splitlines() if 'ss-sticker__media' in l]
        self.assertTrue(img)
        self.assertFalse(any('--live' in l for l in img),
                         'a photo is being positioned as live media')

    def test_inset_is_declared_before_the_offsets(self, _geo):
        """
        `inset` is a shorthand for all four sides. Declared after left/top it
        silently resets them to auto, which put every video and GIF back at
        its static position — visibly misaligned inside the die-cut.
        """
        import os, re
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css = open(os.path.join(
            base, 'stickers/static/stickers/css/sheet.css')).read()
        rule = re.search(r'\.ss-sticker__media--live\s*\{(.*?)\}', css, re.S).group(1)
        self.assertLess(rule.index('inset:'), rule.index('left:'),
                        'inset shorthand comes after left/top and wipes them')
        self.assertLess(rule.index('inset:'), rule.index('top:'),
                        'inset shorthand comes after left/top and wipes them')

    def test_missing_dimensions_degrade_safely(self, _geo):
        s = self._sticker()
        Sticker.all_objects.filter(pk=s.pk).update(media_width=None,
                                                   media_height=None)
        self.assertIsNone(Sticker.objects.get(pk=s.pk).live_crop)
        self.assertEqual(self.client.get(reverse('stickers:sheet')).status_code, 200)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class ReframeVideoTests(TestCase):
    """
    Re-framing a video frames the CLIP, the same as the creator page does with
    a file being chosen. A subject moves, so judging a crop from one frame is
    a poor substitute — and the poster shares the clip's dimensions, so the
    crop that comes out is identical either way.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_superuser('mod5', 'm5@x.com', 'pw')
        self.client.force_login(self.staff)

    def _video_sticker(self):
        species = Species.objects.create(common_name='Jelly')
        s = Sticker.objects.create(
            species=species,
            media=SimpleUploadedFile('clip.mp4', b'\x00\x00\x00\x18ftypmp42',
                                     content_type='video/mp4'),
            status=Sticker.Status.PUBLISHED)
        return s

    def test_reframe_hands_over_the_clip_not_the_still(self, _geo):
        s = self._video_sticker()
        body = self.client.get(reverse('stickers:reframe', args=[s.slug])).content.decode()
        self.assertIn('data-existing-kind="video"', body)
        self.assertIn(s.media.url, body, 'the clip itself is not being framed')

    def test_a_poster_is_offered_as_a_fallback(self, _geo):
        """Firefox will not decode .mov; a blank stage is worse than a still."""
        s = self._video_sticker()
        # The fixture is a header, not a real clip, so ffmpeg extracts no
        # poster from it. Patch the property: what is under test is the view
        # passing a fallback through, not ffmpeg.
        with mock.patch.object(Sticker, 'poster_url',
                               new_callable=mock.PropertyMock,
                               return_value='/media/clip.poster.jpg'):
            body = self.client.get(
                reverse('stickers:reframe', args=[s.slug])).content.decode()
        self.assertIn('data-existing-poster="/media/clip.poster.jpg"', body)

    def test_a_photo_gets_no_poster_fallback(self, _geo):
        species = Species.objects.create(common_name='Anemone')
        s = Sticker.objects.create(species=species, media=a_varied_photo(),
                                   status=Sticker.Status.PUBLISHED)
        body = self.client.get(reverse('stickers:reframe', args=[s.slug])).content.decode()
        self.assertIn('data-existing-kind="image"', body)
        self.assertNotIn('data-existing-poster', body)


class FramerParityTests(TestCase):
    """
    The creator and the re-framer are one editor, and must stay one editor.
    """

    def _js(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(
            base, 'stickers/static/stickers/js/framer.js')).read()

    def test_both_paths_go_through_the_same_attach(self):
        js = self._js()
        # one place builds the media element, whether it came from a file
        # input or from an existing sticker
        self.assertEqual(js.count('function attach('), 1)
        self.assertIn('createObjectURL', js)      # the creator path
        self.assertIn('existingUrl', js)          # the re-frame path

    def test_the_editor_markup_is_not_duplicated(self):
        import glob, os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hits = [p for p in glob.glob(base + '/stickers/templates/**/*.html',
                                     recursive=True)
                if 'data-stage' in open(p).read()]
        self.assertEqual([os.path.basename(p) for p in hits], ['_framer.html'],
                         'the framing editor has been copied, not included')


class AssetLoadingTests(TestCase):
    """
    Turning the static pages into templates swept index.html's script tags
    into the shared base, so every page loaded Bootstrap twice and ran the
    home page's carousel script with no carousel present.
    """

    def test_bootstrap_is_loaded_once_per_page(self):
        for name in ('pages:index', 'pages:contacts', 'pages:kickstarter',
                     'stickers:sheet'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertEqual(body.count('bootstrap.min'), 2,
                             '%s: expected one CSS + one JS bootstrap tag' % name)

    def test_the_carousel_script_is_only_on_the_home_page(self):
        home = self.client.get(reverse('pages:index')).content.decode()
        self.assertIn('carousel-autoplay', home)
        for name in ('pages:contacts', 'pages:kickstarter', 'stickers:sheet'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn('carousel-autoplay', body,
                             '%s loads a carousel script it has no carousel for' % name)

    def test_the_navbar_shrink_is_not_duplicated(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sheet = open(os.path.join(
            base, 'stickers/static/stickers/js/sheet.js')).read()
        self.assertNotIn('navbar-shrink', sheet,
                         'the shrink is back in a gallery-only script')
        for name in ('pages:index', 'stickers:sheet'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertIn('startup-modern', body,
                          '%s has no navbar shrink at all' % name)

    def test_no_hand_rolled_cache_busters(self):
        """Filenames carry a content hash now; ?v= is noise that goes stale."""
        for name in ('pages:index', 'pages:contacts', 'stickers:sheet',
                     'stickers:submit'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn('.css?v=', body, name)
            self.assertNotIn('.js?v=', body, name)

    def test_the_framing_editor_always_brings_its_script(self):
        """
        The re-frame page rendered the editor markup without ever loading
        framer.js, so the stage sat empty — no media, no mask. The partial
        ships the script, so including one without the other cannot happen.
        """
        from django.contrib.auth.models import User
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io as _io
        from PIL import Image as _Image

        buf = _io.BytesIO()
        _Image.new('RGB', (800, 600), (30, 90, 110)).save(buf, 'JPEG')
        species = Species.objects.create(common_name='Anemone')
        with mock.patch('stickers.models.geocode', return_value=None):
            sticker = Sticker.objects.create(
                species=species,
                media=SimpleUploadedFile('p.jpg', buf.getvalue(),
                                         content_type='image/jpeg'),
                status=Sticker.Status.PUBLISHED)

        User.objects.create_superuser('mod6', 'm6@x.com', 'pw')
        self.client.force_login(User.objects.get(username='mod6'))

        for url in (reverse('stickers:submit'),
                    reverse('stickers:reframe', args=[sticker.slug])):
            body = self.client.get(url).content.decode()
            self.assertIn('data-framer', body, '%s has no editor' % url)
            self.assertIn('framer.js', body,
                          '%s renders the editor but never loads it' % url)
            self.assertEqual(body.count('framer.js'), 1,
                             '%s loads the editor script twice' % url)


class MaskPlacementTests(TestCase):
    """
    `mask-size: 100%` is 100% of the element the mask is ON. Live media is
    sized to its crop box — often ~177% of the sticker square — so a mask on
    the media stretches across the scaled video instead of the sticker.

    It only ever looked correct while the media happened to be exactly the
    square's size, which stopped being true the moment framing was applied to
    live media. This bit twice: once in the framing editor, once on the sheet.
    """

    def _css(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(
            base, 'stickers/static/stickers/css/sheet.css')).read()

    def _rule(self, selector):
        import re
        m = re.search(re.escape(selector) + r'\s*\{(.*?)\n\}', self._css(), re.S)
        return m.group(1) if m else ''

    def test_the_mask_is_never_on_a_media_element(self):
        for selector in ('.ss-sticker__media', '.ss-framer__media'):
            self.assertNotIn('mask-image', self._rule(selector),
                             '%s carries the mask; it must sit on the square'
                             % selector)

    def test_the_mask_is_on_the_square_in_both_places(self):
        for selector in ('.ss-sticker__clip', '.ss-framer__clip'):
            rule = self._rule(selector)
            self.assertIn('mask-image', rule, '%s has no mask' % selector)
            self.assertIn('inset: 0', rule,
                          '%s is not the full sticker square' % selector)

    def test_the_card_renders_the_clip_layer(self):
        with mock.patch('stickers.models.geocode', return_value=None):
            species = Species.objects.create(common_name='Anemone')
            Sticker.objects.create(species=species, media=a_varied_photo(),
                                   status=Sticker.Status.PUBLISHED)
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('ss-sticker__clip', body)

    def test_the_card_paints_the_cut_outline_not_the_svg(self):
        """
        The die background must be the PNG the cutter renders. Browsers and
        SVG rasterisers disagree about stroke overflow, and any disagreement
        shows up as a border that does not match the sticker.
        """
        with mock.patch('stickers.models.geocode', return_value=None):
            species = Species.objects.create(common_name='Anemone')
            Sticker.objects.create(species=species, media=a_varied_photo(),
                                   status=Sticker.Status.PUBLISHED,
                                   shape='06-splat')
        body = self.client.get(reverse('stickers:sheet')).content.decode()
        self.assertIn('06-splat.outline.png', body)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class StaffBypassTests(TestCase):
    """
    Staff publish straight away; everyone else still goes through review.

    The form and the serializer still refuse to write `status` — the
    promotion happens in the view, from the authenticated session. That
    distinction is the whole safety of it: nothing in a request body can ask
    to be published.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_superuser('mod7', 'm7@x.com', 'pw')
        self.plain = User.objects.create_user('nobody', 'n@x.com', 'pw')

    def _post(self, **extra):
        data = {'species_name': 'Anemone', 'media': a_photo()}
        data.update(extra)
        return self.client.post(reverse('stickers:submit'), data)

    # --- the public path is unchanged ---------------------------------
    def test_anonymous_submission_still_waits(self, _geo):
        self._post()
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PENDING)

    def test_anonymous_cannot_ask_to_be_published(self, _geo):
        self._post(status='published')
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PENDING)

    def test_a_logged_in_non_staff_user_still_waits(self, _geo):
        """Being authenticated is not the same as being trusted to publish."""
        self.client.force_login(self.plain)
        self._post()
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PENDING)

    # --- staff bypass --------------------------------------------------
    def test_staff_submission_is_published(self, _geo):
        self.client.force_login(self.staff)
        self._post()
        s = Sticker.objects.get()
        self.assertEqual(s.status, Sticker.Status.PUBLISHED)

    def test_staff_land_on_the_sticker_not_the_queue_message(self, _geo):
        self.client.force_login(self.staff)
        r = self._post()
        s = Sticker.objects.get()
        self.assertRedirects(r, s.get_absolute_url())

    def test_staff_sticker_is_on_the_sheet_immediately(self, _geo):
        self.client.force_login(self.staff)
        self._post()
        self.assertContains(self.client.get(reverse('stickers:sheet')), 'Anemone')

    def test_the_form_itself_still_only_writes_pending(self, _geo):
        """The invariant the open upload form depends on."""
        from stickers.forms import SubmitStickerForm
        self.assertNotIn('status', SubmitStickerForm.Meta.fields)
        form = SubmitStickerForm({'species_name': 'Anemone',
                                  'status': 'published'},
                                 {'media': a_photo()})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().status, Sticker.Status.PENDING)

    # --- the API follows the same rule ---------------------------------
    def test_api_anonymous_lands_pending(self, _geo):
        r = self.client.post('/api/submit/', {'species_name': 'Anemone',
                                              'media': a_photo()})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['status'], Sticker.Status.PENDING)

    def test_api_staff_is_published(self, _geo):
        self.client.force_login(self.staff)
        r = self.client.post('/api/submit/', {'species_name': 'Anemone',
                                              'media': a_photo()})
        self.assertEqual(r.json()['status'], Sticker.Status.PUBLISHED)
        self.assertEqual(Sticker.objects.get().status, Sticker.Status.PUBLISHED)

    def test_api_staff_claim_in_the_payload_is_worthless(self, _geo):
        """The promotion reads the session, never the request body."""
        r = self.client.post('/api/submit/', {
            'species_name': 'Anemone', 'media': a_photo(),
            'is_staff': 'true', 'status': 'published',
        })
        self.assertEqual(r.json()['status'], Sticker.Status.PENDING)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class StickerSheetPageTests(TestCase):
    """/stickersheet/ — the drag-and-arrange playground."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _published(self, name='Anemone'):
        species = Species.objects.create(common_name=name)
        return Sticker.objects.create(species=species, media=a_varied_photo(),
                                      status=Sticker.Status.PUBLISHED)

    def test_the_page_is_public(self, _geo):
        self.assertEqual(self.client.get('/stickersheet/').status_code, 200)

    def test_it_is_not_linked_from_the_site(self, _geo):
        """Unlinked on purpose — reachable only if you know it is there."""
        for name in ('pages:index', 'pages:contacts', 'stickers:sheet'):
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn('/stickersheet/', body,
                             '%s links to the playground' % name)

    def test_the_tray_holds_the_die_cut_pngs(self, _geo):
        s = self._published()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('sk__peel', body)
        self.assertIn(s.sticker_url, body)
        self.assertIn('Anemone', body)

    def test_only_published_stickers_are_offered(self, _geo):
        self._published('Live thing')
        species = Species.objects.create(common_name='Waiting thing')
        Sticker.objects.create(species=species, media=a_varied_photo(),
                               status=Sticker.Status.PENDING)
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('Live thing', body)
        self.assertNotIn('Waiting thing', body)

    def test_binned_stickers_are_not_offered(self, _geo):
        s = self._published('Binned thing')
        s.delete()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertNotIn('Binned thing', body)

    def test_a_sticker_with_no_cut_png_is_skipped(self, _geo):
        """The tray is die-cut art; anything without it would be a broken img."""
        s = self._published()
        from django.core.files.storage import default_storage
        default_storage.delete(s._derivative_name('.sticker.png'))
        with mock.patch.object(Sticker, 'sticker_url',
                               new_callable=mock.PropertyMock, return_value=''):
            body = self.client.get('/stickersheet/').content.decode()
        self.assertNotIn('sk__peel', body)

    def test_moving_stickers_carry_their_live_parts(self, _geo):
        """
        A PNG cannot move, so a video sticker is rebuilt on the canvas from
        its parts: outline art, inset mask, media, and the stored crop.
        """
        buf = io.BytesIO()
        Image.new('RGB', (800, 400), (200, 40, 40)).save(buf, 'GIF')
        species = Species.objects.create(common_name='Wriggler')
        Sticker.objects.create(
            species=species,
            media=SimpleUploadedFile('w.gif', buf.getvalue(),
                                     content_type='image/gif'),
            status=Sticker.Status.PUBLISHED, shape='06-splat')
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('data-kind="gif"', body)
        for attr in ('data-media=', 'data-outline=', 'data-mask=', 'data-crop='):
            self.assertIn(attr, body, '%s missing — it cannot animate' % attr)

    def test_the_crop_is_applied_with_units(self, _geo):
        """
        data-crop carries bare numbers. CSS drops a unitless length, so
        applying them raw left the media at the stylesheet's 100%/100% —
        squashed into the square at the wrong aspect ratio.
        """
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js = open(os.path.join(
            base, 'stickers/static/stickers/js/stickersheet.js')).read()
        for prop in ('width', 'height', 'left', 'top'):
            self.assertIn("media.style.%s = c[" % prop, js)
        self.assertEqual(js.count("+ '%'"), 4,
                         'a crop value is being applied without its unit')

    def test_every_sticker_carries_its_outline_and_mask(self, _geo):
        """
        Music mode spins the outline while the picture holds still, so even a
        photograph has to arrive as separate parts — the flat die-cut PNG
        bakes the two together and would turn the animal upside down.
        """
        self._published()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('data-kind="still"', body)
        for attr in ('data-outline=', 'data-mask=', 'data-media='):
            self.assertIn(attr, body, '%s missing for a still' % attr)

    def test_a_still_does_not_ship_video_plumbing(self, _geo):
        self._published()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertNotIn('data-poster=', body)

    def test_the_page_brings_its_own_script(self, _geo):
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('stickersheet.js', body)

    def test_the_sticker_layer_spans_the_page(self, _geo):
        """
        The layer is not a box to arrange things inside — it covers the whole
        document, transparent and click-through, so a sticker can sit over the
        navbar or across a paragraph while the page underneath still works.
        """
        self._published()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('data-canvas', body)
        self.assertIn('sk__layer', body)

        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css = open(os.path.join(
            base, 'stickers/static/stickers/css/sheet.css')).read()
        import re
        layer = re.search(r'\.sk__layer \{(.*?)\}', css, re.S).group(1)
        self.assertIn('pointer-events: none', layer,
                      'the layer would block the page underneath')
        # Bootstrap's .fixed-top navbar is z-index 1030. Anything lower hides
        # stickers behind it, and putting one over the nav is the point.
        z = int(re.search(r'z-index:\s*(\d+)', layer).group(1))
        self.assertGreater(z, 1030,
                           'stickers would sit behind the fixed navbar')
        stuck = re.search(r'\.sk__stuck \{(.*?)\}', css, re.S).group(1)
        self.assertIn('pointer-events: auto', stuck,
                      'placed stickers would not be draggable')

    def test_the_page_content_is_still_there(self, _geo):
        """The point is stickers OVER the page, not instead of it."""
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('Peel an animal off the sticker sheet', body)
        self.assertIn('id="mainNav"', body)
        self.assertIn('dipsticker sheet', body)

    def test_the_page_fits_the_viewport(self, _geo):
        """
        Nothing should scroll: the instructions and the footer are both
        visible without moving, and the tray scrolls inside itself instead.
        """
        import os, re
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        css = open(os.path.join(
            base, 'stickers/static/stickers/css/sheet.css')).read()
        i = css.index('@media (min-height: 640px)')
        block = css[i:i + 700]
        self.assertIn('height: 100vh', block)
        self.assertIn('overflow: hidden', block)
        self.assertIn('.sk-page .sk__tray { height: 100%', block)
        # guarded, because on a short window cutting the footer off is worse
        self.assertIn('min-height: 640px', css)

    def test_placing_is_possible_without_dragging(self, _geo):
        self._published()
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('aria-label="Peel', body)


@override_settings(MEDIA_ROOT=MEDIA)
@mock.patch('stickers.models.geocode', return_value=None)
class AnimalDiscoTests(TestCase):
    """
    Animal disco spins each sticker's OUTLINE around its picture and swells
    it on the beat, listening through the microphone.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _css(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(
            base, 'stickers/static/stickers/css/sheet.css')).read()

    def _js(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(
            base, 'stickers/static/stickers/js/musicmode.js')).read()

    def test_there_is_a_toggle(self, _geo):
        body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('data-music', body)
        self.assertIn('animal disco', body)
        self.assertIn('musicmode.js', body)

    def test_it_spins_at_five_rpm(self, _geo):
        """5rpm is one turn every twelve seconds."""
        css = self._css()
        self.assertIn('animation: sk-orbit 12s linear infinite', css)
        self.assertIn('@keyframes sk-orbit', css)

    def test_the_die_cut_window_turns_with_the_border(self, _geo):
        """Both edges orbit together, or the border and the cut disagree."""
        css = self._css()
        i = css.index('.sk-music .sk__stuck-backing')
        rule = css[i:css.index('}', i)]
        for part in ('.sk__stuck-ring', '.sk__stuck-clip'):
            self.assertIn(part, rule, '%s does not turn with the border' % part)
        self.assertIn('sk-orbit 12s', rule)

    def test_the_picture_is_counter_rotated_at_the_same_rate(self, _geo):
        """
        Otherwise the animal turns upside down with its edge. The counter-turn
        must match the turn exactly — same duration, opposite direction.
        """
        import re
        css = self._css()
        back = re.search(r'\.sk-music \.sk__stuck-spin \{(.*?)\}', css, re.S)
        self.assertIsNotNone(back)
        self.assertIn('sk-orbit-back 12s', back.group(1))
        self.assertIn('@keyframes sk-orbit-back { to { transform: rotate(-360deg); } }',
                      css)

    def test_the_media_itself_never_spins(self, _geo):
        """
        The picture holds still while its edge orbits. The counter-rotation is
        on the wrapper, not the media — the media's own centre is offset from
        the square by the crop, so turning it about itself would swing it
        around instead of holding it in place.
        """
        import re
        css = self._css()
        m = re.search(r'\.sk__stuck-media \{(.*?)\n\}', css, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn('animation', m.group(1),
                         'the picture spins; only its edge should')

    def test_the_picture_sits_behind_the_border(self, _geo):
        """
        Once the die-cut window turns, a picture painted OVER the vinyl can
        swing past the orbiting edge and escape the sticker. Behind a ring
        with a punched-out middle, it is always framed.
        """
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js = open(os.path.join(
            base, 'stickers/static/stickers/js/stickersheet.js')).read()
        order = [js.index("wrap.appendChild(backing)"),
                 js.index("wrap.appendChild(clip)"),
                 js.index("wrap.appendChild(ring)")]
        self.assertEqual(order, sorted(order),
                         'the border is not painted over the picture')

    def test_the_ring_art_has_a_hole_in_it(self, _geo):
        """An opaque centre would hide the animal completely."""
        import os
        from PIL import Image as _Image
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ring = _Image.open(os.path.join(
            base, 'stickers/static/stickers/shapes/06-splat.ring.png'))
        w, h = ring.size
        self.assertEqual(ring.getpixel((w // 2, h // 2))[3], 0,
                         'the ring has no hole; it would cover the picture')
        band = sum(1 for p in ring.getchannel('A').getdata() if p > 128)
        self.assertGreater(band, 0, 'the ring is entirely empty')

    def test_the_counter_rotation_wrapper_is_the_full_square(self, _geo):
        """It has to share the clip's centre for the turns to cancel."""
        import re
        css = self._css()
        m = re.search(r'\.sk__stuck-spin \{(.*?)\}', css, re.S)
        self.assertIsNotNone(m)
        self.assertIn('inset: 0', m.group(1))

    def test_the_beat_does_not_disturb_the_arrangement(self, _geo):
        """
        The pulse multiplies into the sticker's existing transform, so a beat
        cannot undo a rotation or a flip someone set.
        """
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js = open(os.path.join(
            base, 'stickers/static/stickers/js/stickersheet.js')).read()
        self.assertIn('scale(var(--pulse, 1))', js)
        self.assertIn("rotate(' + it.rot + 'deg)", js)

    def test_the_mic_is_only_asked_for_on_a_gesture(self, _geo):
        """Requesting it on load would be refused, and rude."""
        js = self._js()
        self.assertIn('getUserMedia', js)
        i_click = js.index("button.addEventListener('click'")
        i_listen = js.index('async function listen')
        self.assertGreater(i_click, i_listen,
                           'the mic must be requested from the toggle handler')

    def test_a_refused_mic_still_spins(self, _geo):
        """The spin is the bigger half and costs nothing."""
        js = self._js()
        self.assertIn('catch (err)', js)
        self.assertIn('No microphone', js)

    def test_the_mic_is_released_when_switched_off(self, _geo):
        """Leaving a live mic open after the toggle is off is not on."""
        js = self._js()
        self.assertIn('t.stop()', js)
        self.assertIn('audio.close()', js)

    def test_reduced_motion_stops_the_spin(self, _geo):
        """Spinning is exactly what someone with vestibular trouble opted out of."""
        css = self._css()
        # the LAST such block is the disco one; there is an earlier, unrelated
        # reduced-motion block for the sheet cards
        i = css.rindex('prefers-reduced-motion')
        self.assertIn('animation: none', css[i:])


class ScaleGestureTests(TestCase):
    """
    Resizing is shift + scroll. It used to be a held 'S' key, which could be
    left stuck on if the window lost focus mid-press.
    """

    def _js(self):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(
            base, 'stickers/static/stickers/js/stickersheet.js')).read()

    def test_resize_is_shift_scroll(self):
        js = self._js()
        self.assertIn('if (!e.shiftKey) { return; }', js)

    def test_no_held_key_state_remains(self):
        """A modal key with no keyup is a stuck mode waiting to happen."""
        self.assertNotIn('scaleKeyDown', self._js())

    def test_plain_scrolling_still_scrolls(self):
        """Hijacking the wheel outright would trap the page."""
        js = self._js()
        i = js.index("addEventListener('wheel'")
        self.assertIn('return;', js[i:i + 400])

    def test_the_legend_matches_the_gesture(self):
        with mock.patch('stickers.models.geocode', return_value=None):
            body = self.client.get('/stickersheet/').content.decode()
        self.assertIn('<kbd>shift</kbd>+scroll resize', body)
        self.assertNotIn('<kbd>s</kbd>+scroll', body)
