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
API: `/api/stickers/`, `/api/species/`, `/api/submit/`.

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

## Derivative-file pipeline (non-obvious)

`Sticker.media` writes derivatives **alongside the original** in `media/captures/<year>/<month>/`:

| Derivative | Purpose | Tool |
| --- | --- | --- |
| `<base>.sticker.png` | the die-cut sticker — transparent, white vinyl border, ink keyline | Pillow |
| `<base>.thumb.jpg` | 640px square grid thumbnail | Pillow |
| `<base>.lowres.jpg` | 32px LQIP placeholder, unblurred by `sheet.js` | Pillow |
| `<base>.poster.jpg` | video only: frame at 1s, then fed through the three above | ffmpeg |

Pattern, same as workshops.dipstick.earth's carousel:
- Built synchronously in `Sticker.save()`. A video takes a few seconds (ffmpeg).
- Each `*_url` property **lazily rebuilds** if the file is missing, which backfills anything that
  failed to write (e.g. saved as the wrong user).
- Errors are swallowed (`except Exception: pass`) so a corrupt upload can't 500 the submit form;
  the property returns `''` and templates fall back to the original.

**Gotcha that already bit once:** `save()` decides whether to rebuild using `self._state.adding`,
captured *before* `super().save()`. It cannot just compare `media.name` to the `__init__`
snapshot, because `upload_to` rewrites the name during the first save and `__init__` already
snapshotted the incoming value — both would compare equal and a new row would never build
derivatives or geocode. `test_derivatives_are_built_on_save` and
`test_location_is_geocoded_once` cover this.

To rebuild by hand, use the admin action "Rebuild sticker PNG / thumbnails", or in a shell
`s.build_derivatives()`. **Run it as the user that owns `media/`** — as with the workshops site,
a permissions failure is swallowed silently.

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

## Filesystem permissions

`media/` and `staticfiles/` are group `www-data` and group-writable — apache writes uploads and
their derivatives. `local_settings.py` is `japhy:www-data` `640`. Anything that resets these to
`japhy:japhy` breaks uploads or boots the app into dev settings.

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

## Still to do

- Nothing seeds the sheet yet — it is empty by design; the first real submissions fill it.
- The HTML submit form has no rate limit (the API one does).
- `SECURE_HSTS_SECONDS` is unset, so `check --deploy` warns. Enable only deliberately — HSTS is
  hard to walk back, and it would apply to the whole `dipstick.earth` tree if set with
  `includeSubDomains`.
