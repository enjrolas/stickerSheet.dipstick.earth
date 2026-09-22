# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Django 4.2 + MySQL backend, JSON API and gallery for **stickerSheet.dipstick.earth** — the
"Gallery" that dipstick.earth's nav and footer link to from 5 places. People submit a photo or
clip of whatever they found down a dipstick; the app turns it into a die-cut sticker and, once a
human approves it, sticks it on the sheet.

Project `stickersheet`, one app `stickers`:

- `Species` — common/scientific name, slug, coarse `group` (fish, invertebrate, bird…). The
  chips across the top of the sheet filter on `group`.
- `Sticker` — one capture: media file, species FK, caption, `wildlife_investigator` (the credit),
  free-text `location` (geocoded), `captured_at`, and a `status` of pending/published/rejected.

Pages: `/` the sheet, `/sticker/<slug>/`, `/species/<slug>/`, `/submit/`.

API:

| Endpoint | What |
| --- | --- |
| `GET /api/stickers/` | published stickers; `?species= ?group= ?kind= ?q=` |
| `GET /api/stickers/<slug>/` | one sticker |
| `GET /api/stickers/<slug>/svg/` | **that sticker as an SVG file** |
| `GET /api/species/` | species with at least one published sticker |
| `GET /api/shapes/` | the ten die-cut outlines, with their raw path data |
| `POST /api/submit/` | open, throttled `12/hour`, always lands pending |

## Deleting a sticker is soft — and must stay that way

**A submitted photo is the only copy.** On 2026-09-22 a cleanup ran
`Sticker.objects.all().delete()` against the live database and destroyed a real submission and
its file along with two test rows. Soft delete exists so that cannot happen again.

- `Sticker.objects` — the default manager, **live rows only**.
- `Sticker.all_objects` — everything, including the bin. Used by the admin and for restores.
- `.delete()`, on an instance or a queryset, stamps `deleted_at` and **returns without touching
  the file**. `Sticker.objects.all().delete()` is now harmless.
- `.restore()` clears it. `.hard_delete()` really removes the row, and only
  `hard_delete(delete_file=True)` ever unlinks an upload.
- `Meta.base_manager_name = 'all_objects'` so FK traversal still resolves for a binned row.

**The trap, if you add a query:** an annotation or a `filter()` that *joins* to stickers runs in
SQL and does **not** go through the manager, so it will happily count rows in the bin. Those
joins have to spell out `stickers__deleted_at__isnull=True` by hand — see `api.SpeciesViewSet`
and `views.sheet`. `test_counts_ignore_binned_stickers` covers it.

In the admin, the changelist reads from `all_objects` and a **Bin** filter hides deleted rows by
default; switch it to "In the bin" to see and restore them. The built-in "Delete selected" is
soft. The Restore action resolves its selection from the POST rather than the filtered queryset,
because on the default view the binned rows are not in that queryset at all.

**There is still no database backup.** Soft delete protects against an accidental delete, not
against a dropped table or a disk failure.

## Moderation is the whole security model

**Every public submission lands `pending` and nothing renders it until a staff user publishes
it.** That gate is the reason the upload form can be open at all. Three places enforce it, and
all three have tests in `stickers/tests.py` — don't weaken one without checking the others:

- `SubmitStickerForm.Meta.fields` has no `status`, and `save()` hard-sets `PENDING`.
- `StickerSubmitSerializer.Meta.fields` has no `status` either, so `POST status=published` is
  ignored (`test_api_cannot_publish_itself`).
- Every read path goes through `status=PUBLISHED` (`views._published()`, `api.published()`).

`submitter_email` is collected but is **never** in a serializer's `fields` and never rendered in
a template — `test_submitter_email_is_never_exposed` guards that. Keep it that way.

Spam control is a honeypot field (`website`, hidden — bots fill it, people don't) plus DRF's
`ScopedRateThrottle` at `12/hour` on the API submit endpoint. The HTML form is not throttled;
if that ever gets abused, that is the first thing to add.

## Python version + venv (read this first)

`mod_wsgi` on this server links **libpython3.8** (`ldd /usr/lib/apache2/modules/mod_wsgi.so |
grep python`). The system `python3` is 3.9. **`.venv/` MUST be Python 3.8.** If you blow it away:
`python3.8 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

Anything that should match the apache process runs via `.venv/bin/python`, not `python3`:

```
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
```

## Reloading the running app

```
touch stickersheet/wsgi.py
```

mod_wsgi watches that mtime and recycles the daemon. CSS/JS edits also need `collectstatic` —
apache serves `/static/` from `staticfiles/` via `Alias`, not from the app's static dir. Bust the
browser cache by bumping `?v=N` on the `sheet.css` link in `base.html`.

## Secrets — `stickersheet/local_settings.py`

`settings.py` ends with `try: from .local_settings import * except ImportError: pass`. The
gitignored `local_settings.py` holds the real `SECRET_KEY`, `DEBUG = False`, `ALLOWED_HOSTS` and
the MySQL password. **Do not move secrets into settings.py** — the pattern is intentional for
mod_wsgi (no env-var gymnastics). `local_settings.py.example` is the template.

**That file must be readable by apache.** It is `japhy:www-data` mode `640`. If it ever reverts
to `japhy:japhy`, every request 500s with `ImproperlyConfigured` — the import silently falls
through to the dev defaults and then `ALLOWED_HOSTS` rejects the host.

## Database

MySQL 8, database and user both `stickerSheet`, password in `local_settings.py`. utf8mb4,
`STRICT_TRANS_TABLES`.

**The `stickerSheet` user cannot create `test_stickerSheet`**, so `manage.py test` fails against
MySQL. Either grant it:

```sql
GRANT ALL PRIVILEGES ON `test_stickerSheet`.* TO 'stickerSheet'@'%'; FLUSH PRIVILEGES;
```

...or run the suite on in-memory SQLite:

```
.venv/bin/python manage.py test stickers --settings=stickersheet.test_settings
```

The SQLite route is fast and covers the logic, but it will **not** catch MySQL-specific problems
(collation, strict-mode rejections, index length). Prefer the grant before any schema change.

## Die-cut outlines — `stickers/shapes/`

Ten hand-drawn SVG silhouettes (soft rectangle, capsule, scalloped badge, cloud blob, wobbly
oval, splat, three bursts, melted label), each a 512x512 viewBox with one closed path
`id="sticker-shape"`. **A sticker is cropped to one of these**, and that is what makes it a
sticker rather than a photo in a box.

`stickers/shapes.py` parses them itself — they only use `M`/`L`/`C`/`Z`, so it flattens the
cubics and fills the polygon with Pillow rather than depending on cairosvg (needs libcairo) or
ImageMagick's flaky SVG delegate. **If a new outline uses arcs (`A`) or quadratics (`Q`) the
parser silently skips the command and the shape comes out wrong** — add the case.

`shapes.mask(pts, size, inset=N)` does a **true uniform inset** — a morphological erosion by a
disc, stamped as overlapping circles along a densified outline. **Two earlier approaches were
wrong**; both are easy to "simplify" back into, so don't:

1. **Scaling the polygon toward its centroid.** On a starburst that *shortens* the spikes instead
   of thinning them, so the photo reached into the points and there was no white border there. A
   real uniform inset eats the narrow wedges away entirely — which is why the inset bounding box
   is much smaller than the outline's on spiky shapes. That is correct, and
   `test_inset_eats_inward_everywhere` pins it.
2. **Stroking the outline** with `ImageDraw.line(width=2*inset, joint='curve')`. Geometrically
   right, but Pillow's wide-line renderer leaves unfilled slivers at large widths, which showed
   up as hairline whiskers radiating across the white border — subtle at 512px, obvious at 1024.

Disc stamping has no such failure mode: every pixel within `inset` of the boundary is covered by
construction. `_densify` keeps the step at `radius * 0.2`; the union of discs scallops between
centres with amplitude `~radius * (1 - cos(asin(step/2r)))`, and 0.5 left a ripple visible on the
cut edge. A 1024px mask takes ~0.15s.

`Sticker.shape` picks the outline; blank means auto, derived from the pk so it is stable across
rebuilds and spreads the ten shapes down the sheet. The admin dropdown is built from the files on
disk (`formfield_for_dbfield`), so **dropping a new SVG into `stickers/shapes/` needs no
migration** — just rerun `build_shape_masks` and `collectstatic`.

## Framing — the crop is chosen in the browser, applied on the server

`Sticker.focal_x`, `focal_y` and `zoom` say which square of the source becomes the sticker:
`focal_*` is the point (0..1 of width/height) that lands in the middle, `zoom` 1.0 takes the
largest square that fits. `imaging.focal_crop()` turns those three numbers into a rectangle,
clamped so dragging to an edge stops rather than letting blank space in.

**That rule is deliberately duplicated in `static/stickers/js/framer.js`**, which is what makes
the live preview on `/submit/` honest — the stage shows exactly the square that will be cut.
Change one, change the other. The crop rounds the *side* once and derives both edges from it;
rounding each edge separately produced e.g. 402x401, which then got squashed into a square
(`test_crop_is_always_square`).

The submit page also offers the ten outlines as a visual picker (plus "surprise me", which leaves
`shape` blank and lets the pk decide). The form validates `shape` against the files on disk and
clamps the framing, so nothing the browser posts can escape those ranges.

## Cropping video and GIFs — why there are two mechanisms

Pillow cannot crop a moving image, so the outline is applied twice, from the same source SVG:

| Where | How | Covers |
| --- | --- | --- |
| The downloadable `.sticker.png` | Pillow, server-side, per upload | stills only (a video uses its poster frame) |
| The gallery card | CSS `mask-image`, in the browser | photo, **animated GIF and video** alike |

`manage.py build_shape_masks` writes both static files the gallery needs into
`stickers/static/stickers/shapes/`: `<slug>.svg` (painted behind the media as the white vinyl
border) and `<slug>.mask.png` (the inset silhouette the media is clipped to). **Rerun it after
touching a shape, then `collectstatic`** — otherwise the moving stickers and the downloadable
PNGs drift apart.

The card markup lives in one partial, `templates/stickers/_sticker_card.html`, included by the
sheet, species and detail pages. It picks the element by media type: `<video>` for video (source
attached and played only while on screen, by `sheet.js`), a plain `<img>` pointing at the
**original** file for a GIF (a thumbnail would freeze it), and the LQIP-then-thumbnail dance for
a photo. `Sticker.is_gif` is extension-based because a GIF is stored as `media_kind=image`.

The hard offset shadow is `filter: drop-shadow(...)` rather than `box-shadow`, so it follows the
die-cut alpha instead of tracing a rectangle. There is an `@supports not (mask-image:...)`
fallback to a rounded corner for older engines.

## Serving a sticker as SVG — `stickers/svg.py`

`GET /api/stickers/<slug>/svg/` returns `image/svg+xml`:

- `?embed=1` inlines the artwork as a base64 data URI, so the file stands alone
  (~197 KB). Without it the `<image>` links back to this server (~1.9 KB).
- `?download=1` adds `Content-Disposition: attachment`.
- A video embeds its **poster frame** — SVG `<image>` cannot play video.
- Only published stickers resolve; a pending one 404s, same as every other read path.

**The SVG and the PNG must stay cut with the identical outline** — they sit next to each other on
the detail page. `test_svg_uses_the_same_outline_as_the_png` pins that.

Both get their uniform border the same way, and it is not obvious: **clip to the outline, then
stroke that same outline from inside the clip.** Half the stroke falls outside and is clipped
away, leaving exactly `width / 2` lying inside the edge. That is why the stroked paths live
inside the `<g clip-path=...>` — move them out and half the border hangs past the die-cut edge.
`test_border_is_stroked_inside_the_clip` guards it. (Pillow does the same thing with
`draw.line` over the filled polygon; see the shapes section.)

`/api/shapes/` reads the SVGs off disk and returns each outline's `slug`, `label`, static `svg`
and `mask_png` URLs, and its raw `path` data — so a client can draw the silhouette itself. A new
outline appears there with no migration and no code change.

## Derivative-file pipeline (non-obvious)

`Sticker.media` writes derivatives **alongside the original** in `media/captures/<year>/<month>/`:

| Derivative | Purpose | Tool |
| --- | --- | --- |
| `<base>.sticker.png` | the die-cut sticker — transparent, cut to the shape | Pillow |
| `<base>.thumb.jpg` | 640px square grid thumbnail | Pillow |
| `<base>.lowres.jpg` | 32px LQIP placeholder, unblurred by `sheet.js` | Pillow |
| `<base>.poster.jpg` | video only: frame at 1s, then fed through the three above | ffmpeg |

Pattern, same as workshops.dipstick.earth's carousel:
- Built synchronously in `Sticker.save()`. A video takes a few seconds (ffmpeg).
- Each `*_url` property **lazily rebuilds** if the file is missing, which backfills anything that
  failed to write.
- Errors are swallowed (`except Exception: pass`) so a corrupt upload can't 500 the submit form;
  the property returns `''` and templates fall back to the original.

**Gotcha that already bit once:** `save()` decides whether to rebuild using `self._state.adding`,
captured *before* `super().save()`. It cannot just compare `media.name` to the `__init__`
snapshot, because `upload_to` rewrites the name during the first save and `__init__` already
snapshotted the incoming value — both would compare equal and a new row would never build
derivatives or geocode. `test_derivatives_are_built_on_save` and
`test_location_is_geocoded_once` cover this.

## Geocoding

`Sticker.location` (free text) is geocoded via Nominatim on save and stored in
`latitude`/`longitude`, which drives the OpenStreetMap iframe on the detail page. It only re-runs
when `location` changes, and silently no-ops on network failure (lat/lng just stay `None`).
`stickers/tests.py` mocks `stickers.models.geocode` — **patch that name, not `geocode.geocode`**,
since `models` imports the function directly.

## Apache vhost pair — `deploy/`

Kept in the repo as the canonical config, same split as workshops.dipstick.earth:

- `deploy/stickersheet.dipstick.earth.conf` — port 80, **redirect only, no WSGI**
- `deploy/stickersheet.dipstick.earth-le-ssl.conf` — port 443, all the WSGI + alias config

The split is deliberate: certbot's `--apache` plugin clones the HTTP vhost into the SSL one, and
a duplicate `WSGIDaemonProcess` name makes mod_wsgi refuse to start. The :80 vhost also excludes
`/.well-known/acme-challenge/` from its redirect, so a first-time cert issuance isn't bounced to
an https URL that doesn't work yet.

To deploy a vhost edit:

```
sudo install -m 644 deploy/stickersheet.dipstick.earth-le-ssl.conf \
  /etc/apache2/sites-available/stickersheet.dipstick.earth-le-ssl.conf
sudo apache2ctl configtest && sudo systemctl reload apache2
```

**Surviving a reboot** needs nothing extra: `apache2` and `mysql` are both `systemctl enabled`,
the `a2ensite` symlink persists, and mod_wsgi's daemon is started by apache itself. There is no
gunicorn and no separate unit to babysit.

`mod_php8.3 is enabled server-wide on this box`, so the `/media/` Directory block turns the PHP
engine off, strips handlers and forces `text/plain` on anything script-shaped. The form only
accepts image/video extensions; that block is the second lock, not the first. **Don't drop it.**

## Filesystem permissions — this caused a live 500

Uploads are written by **apache (`www-data`)** for a public submission and by **`japhy`** for a
shell import, and both have to be able to write the same tree. Getting this wrong fails in the
worst way: `build_derivatives()` swallows the error, so it goes quiet rather than loud.

The 500 that actually happened: `media/` was `japhy:www-data` `775`, but the dated subdirectories
`media/captures/2026/09/` had been created from a shell as `japhy:japhy` `755`, so apache could
not write into them. `PermissionError: [Errno 13]` on the first real form submission.

Three things keep it fixed — **all three matter**:

1. On disk, `media/` and everything under it is group `www-data`, group-writable, and carries the
   **setgid bit** so newly created subdirectories stay group `www-data`:
   `chgrp -R www-data media && chmod -R g+w media && find media -type d -exec chmod g+s {} \;`
2. `FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o775` and `FILE_UPLOAD_PERMISSIONS = 0o664` in
   settings, so the dated directories Django creates are group-writable from the start.
3. `imaging.DERIVATIVE_MODE = 0o664`, chmodded onto every derivative after it is written.
   Pillow and ffmpeg go through the process umask and land `0644`, which would leave files the
   *other* user could never overwrite.

`local_settings.py` is `japhy:www-data` `640`. `staticfiles/` is group `www-data`.

## Logging — where a 500 actually goes

Django's default `LOGGING` only mails `ADMINS`. With `DEBUG = False` and no mail configured, a
500 leaves **no traceback anywhere** — the apache error log shows only mod_wsgi chatter, which
is exactly how the permissions bug above hid. `settings.py` therefore defines a `LOGGING` dict
writing `django.request` at ERROR to:

```
/home/japhy/logs/stickersheet-django.log
```

(rotating, 5 MB x 3). That file is `japhy:www-data` `664` — **apache must be able to write it**,
or the handler itself throws on startup. Check it first when something 500s.

## Cross-origin assets

`base.html` hot-links from `https://dipstick.earth/assets/` rather than vendoring a second copy:
`bootstrap/css/bootstrap.min.css`, `bootstrap/js/bootstrap.min.js`, `css/Chillax%20Variable.css`
(note the URL-encoded space), and `img/dipstick-mark.png`. Hanken Grotesk comes from Google.

The favicon and `dipstick-sticker.png` are **local static**, generated from
`/home/japhy/workshops.dipstick.earth/basic dipstick sticker.png` (1024², alpha-padded — crop to
`getbbox()` first, content is 914x870). Note dipstick.earth's own copy is only the 100px
`basic dipstick sticker resized.png`; use the workshops one for anything that needs resolution.

`CORS_ALLOWED_ORIGINS` lets dipstick.earth and workshops.dipstick.earth read the API (GET only)
so either can embed the sheet later.

## The design

Same visual language as dipstick.earth's "Sticker Sheet": cream `--paper`, hard offset shadows
(`--pop`), Chillax display over Hanken Grotesk. **Tokens are copied into
`stickers/static/stickers/css/sheet.css`, not imported**, so this site keeps working if the
parent stylesheet moves — if you retheme dipstick.earth, update both.

Stickers sit at a tilt derived from the pk (`stickerfx.tilt`) so the angle is stable across
reloads; hover straightens and lifts them. `prefers-reduced-motion` drops the tilt and
transitions entirely.

## Django template comments — `{# #}` is single-line only

**A multi-line `{# ... #}` is not a comment at all.** Django only recognises it within one line;
spread it over three and the entire block renders as visible text on the page. That shipped to
the live sheet once, from the top of `_sticker_card.html`. Use `{% comment %} ... {% endcomment %}`
for anything longer than a line. `test_no_multiline_hash_comments_in_templates` scans every
template for it.

## Still to do

- Nothing seeds the sheet yet — it is empty by design; the first real submissions fill it.
- The HTML submit form has no rate limit (the API one does, `12/hour`).
- Video is served as uploaded — there is no compressed/`+faststart` derivative like the workshops
  carousel builds. A long phone clip will be slow on the sheet.
- `SECURE_HSTS_SECONDS` is unset, so `check --deploy` warns. Enable only deliberately — HSTS is
  hard to walk back and would apply to the whole `dipstick.earth` tree with `includeSubDomains`.
