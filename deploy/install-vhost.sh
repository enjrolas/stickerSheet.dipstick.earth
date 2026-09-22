#!/usr/bin/env bash
#
# One-shot vhost install for stickerSheet.dipstick.earth.
#
#   sudo ./deploy/install-vhost.sh
#
# Idempotent: safe to re-run after editing either .conf. It config-tests
# before every reload and bails out rather than leaving apache unable to
# start — a bad config here would take down every other vhost on the box.

set -euo pipefail

SITE=stickersheet.dipstick.earth
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVAIL=/etc/apache2/sites-available

if [[ $EUID -ne 0 ]]; then
    echo "This needs root: sudo $0" >&2
    exit 1
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Installing the port-80 vhost"
install -m 644 "$HERE/$SITE.conf" "$AVAIL/$SITE.conf"
a2ensite "$SITE" >/dev/null
apache2ctl configtest
systemctl reload apache2
echo "http://$SITE is live (redirects to https once the cert exists)"

if [[ ! -f "/etc/letsencrypt/live/$SITE/fullchain.pem" ]]; then
    say "Requesting a Let's Encrypt certificate"
    # --apache writes its own -le-ssl.conf; we overwrite it below with the
    # real one, which is the only copy that carries the WSGI config.
    certbot --apache -d "$SITE" --non-interactive --agree-tos \
            --email alex@alexhornstein.com --redirect
else
    echo "Certificate already present, skipping certbot."
fi

say "Installing the port-443 vhost (WSGI lives here)"
install -m 644 "$HERE/$SITE-le-ssl.conf" "$AVAIL/$SITE-le-ssl.conf"
a2ensite "$SITE-le-ssl" >/dev/null

if ! apache2ctl configtest; then
    echo "configtest FAILED — not reloading. Apache is still serving the old config." >&2
    exit 1
fi
systemctl reload apache2

say "Verifying"
sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$SITE/" || echo 000)
echo "GET https://$SITE/ -> $code"
if [[ "$code" == "200" ]]; then
    echo
    echo "Done. The sheet is at https://$SITE/ and the admin at https://$SITE/admin/"
else
    echo
    echo "Not 200 yet. Check: tail -n 40 /home/japhy/logs/$SITE-error.log" >&2
fi
