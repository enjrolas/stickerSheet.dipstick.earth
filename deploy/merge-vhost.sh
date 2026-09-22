#!/usr/bin/env bash
#
# Point dipstick.earth at the merged Django site.
#
#   sudo ./deploy/merge-vhost.sh            # do it
#   sudo ./deploy/merge-vhost.sh --rollback # put the static site back
#
# The old static vhost is backed up first and the rollback restores it, so
# this is reversible in one command. Nothing is deleted from
# /home/japhy/dipstick.earth — that directory stays exactly as it is.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVAIL=/etc/apache2/sites-available
BACKUP=/root/dipstick-vhost-backup
SITE=dipstick.earth
OLD=stickersheet.dipstick.earth

[[ $EUID -eq 0 ]] || { echo "needs root: sudo $0 $*" >&2; exit 1; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ "${1:-}" == "--rollback" ]]; then
    say "Restoring the static dipstick.earth"
    [[ -d $BACKUP ]] || { echo "no backup at $BACKUP" >&2; exit 1; }
    cp -a "$BACKUP/$SITE.conf" "$AVAIL/$SITE.conf"
    cp -a "$BACKUP/$SITE-le-ssl.conf" "$AVAIL/$SITE-le-ssl.conf"
    [[ -f "$BACKUP/$OLD-le-ssl.conf" ]] && \
        cp -a "$BACKUP/$OLD-le-ssl.conf" "$AVAIL/$OLD-le-ssl.conf"
    apache2ctl configtest
    systemctl reload apache2
    echo "Rolled back. https://$SITE/ is the static site again."
    exit 0
fi

say "Backing up the current vhosts to $BACKUP"
mkdir -p "$BACKUP"
for f in "$SITE.conf" "$SITE-le-ssl.conf" "$OLD-le-ssl.conf"; do
    [[ -f "$AVAIL/$f" ]] && cp -a "$AVAIL/$f" "$BACKUP/$f" && echo "  saved $f"
done

say "Installing the merged dipstick.earth vhost"
install -m 644 "$HERE/$SITE.conf"        "$AVAIL/$SITE.conf"
install -m 644 "$HERE/$SITE-le-ssl.conf" "$AVAIL/$SITE-le-ssl.conf"
a2ensite "$SITE" >/dev/null
a2ensite "$SITE-le-ssl" >/dev/null

if ! apache2ctl configtest; then
    echo "configtest FAILED — restoring the backup, apache untouched." >&2
    cp -a "$BACKUP/$SITE.conf" "$AVAIL/$SITE.conf"
    cp -a "$BACKUP/$SITE-le-ssl.conf" "$AVAIL/$SITE-le-ssl.conf"
    exit 1
fi
systemctl reload apache2

say "Checking the merged site before touching the old host"
sleep 3
ok=1
for path in / /contacts/ /kickstarter/ /gallery/ /gallery/submit/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$SITE$path" || echo 000)
    printf '  %-20s %s\n' "$path" "$code"
    [[ "$code" == "200" ]] || ok=0
done

if [[ $ok -ne 1 ]]; then
    echo
    echo "Something is not answering 200. The old host is untouched, so the" >&2
    echo "gallery still works. Roll back with:" >&2
    echo "    sudo $0 --rollback" >&2
    echo "Logs: tail -n 40 /home/japhy/logs/$SITE-error.log" >&2
    exit 1
fi

say "Turning $OLD into a redirect"
install -m 644 "$HERE/stickersheet-redirect-le-ssl.conf" "$AVAIL/$OLD-le-ssl.conf"
if ! apache2ctl configtest; then
    echo "configtest FAILED on the redirect — restoring it." >&2
    cp -a "$BACKUP/$OLD-le-ssl.conf" "$AVAIL/$OLD-le-ssl.conf"
    exit 1
fi
systemctl reload apache2

say "Done"
echo "  https://$SITE/            the site"
echo "  https://$SITE/gallery/    the sheet"
echo "  https://$OLD/             301 -> /gallery/"
echo
echo "Roll back at any time with:  sudo $0 --rollback"
