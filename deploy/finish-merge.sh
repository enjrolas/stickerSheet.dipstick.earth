#!/usr/bin/env bash
#
# Finish the merge: stop running two copies of the same app.
#
#   sudo ./deploy/finish-merge.sh
#
# merge-vhost.sh installs dipstick.earth and only then turns
# stickersheet.dipstick.earth into a redirect. That last step did not take, so
# both vhosts are still serving the full Django app — two sets of mod_wsgi
# daemons, ~140 MB each, for one site. This finishes the job and trims
# dipstick.earth's daemon to a single process.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVAIL=/etc/apache2/sites-available
OLD=stickersheet.dipstick.earth

[[ $EUID -eq 0 ]] || { echo "needs root: sudo $0" >&2; exit 1; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

mkdir -p /root/dipstick-vhost-backup
cp -a "$AVAIL/$OLD-le-ssl.conf" "/root/dipstick-vhost-backup/$OLD-le-ssl.conf.pre-redirect" 2>/dev/null || true

say "Confirming the merged site answers before removing the old one"
ok=1
for path in / /contacts/ /kickstarter/ /gallery/ /gallery/submit/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "https://dipstick.earth$path" || echo 000)
    printf '  %-20s %s\n' "$path" "$code"
    [[ "$code" == "200" ]] || ok=0
done
[[ $ok -eq 1 ]] || { echo "Not all 200 — leaving both vhosts alone." >&2; exit 1; }

say "Replacing the old host with a redirect (frees its WSGI daemons)"
install -m 644 "$HERE/stickersheet-redirect-le-ssl.conf" "$AVAIL/$OLD-le-ssl.conf"

say "Applying the trimmed dipstick.earth daemon (1 process, recycling)"
install -m 644 "$HERE/dipstick.earth-le-ssl.conf" "$AVAIL/dipstick.earth-le-ssl.conf"

if ! apache2ctl configtest; then
    echo "configtest FAILED — restoring the old host, nothing reloaded." >&2
    cp -a "/root/dipstick-vhost-backup/$OLD-le-ssl.conf.pre-redirect" "$AVAIL/$OLD-le-ssl.conf"
    exit 1
fi

say "Reloading"
# A reload makes every WSGI app on this box re-import Django at once, which
# spikes load for a minute or two on a machine this size. That is expected.
systemctl reload apache2
sleep 8

say "Checking"
printf '  %-38s %s\n' "https://dipstick.earth/gallery/" \
    "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 https://dipstick.earth/gallery/)"
printf '  %-38s %s -> %s\n' "https://$OLD/" \
    "$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 https://$OLD/)" \
    "$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 25 https://$OLD/)"
echo
echo "Load will settle over the next couple of minutes. Watch it with:  uptime"
