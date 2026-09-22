"""
Recover the real client IP when the site is served through Cloudflare.

dipstick.earth is a proxied Cloudflare record, so every request arrives at
apache from a Cloudflare edge address. Django's REMOTE_ADDR is therefore the
same handful of values for everybody, and anything that keys on it — most
importantly DRF's submit throttle — stops distinguishing between people. One
submitter would exhaust the 12/hour limit for the whole internet.

Cloudflare puts the original address in CF-Connecting-IP. That header is only
trustworthy when the connection itself came from Cloudflare: the origin is
still reachable directly (stickersheet.dipstick.earth resolves straight to the
Linode), so anyone could set the header by hand and pick their own throttle
bucket. This middleware therefore only honours it when REMOTE_ADDR is inside a
published Cloudflare range.

The ranges below are Cloudflare's published lists (cloudflare.com/ips). They
change rarely, but they do change — refresh with:

    curl https://www.cloudflare.com/ips-v4 https://www.cloudflare.com/ips-v6
"""

import ipaddress
import logging

logger = logging.getLogger('stickers')

CLOUDFLARE_RANGES = [
    # IPv4
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22',
    '103.31.4.0/22', '141.101.64.0/18', '108.162.192.0/18',
    '190.93.240.0/20', '188.114.96.0/20', '197.234.240.0/22',
    '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    # IPv6
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32',
    '2405:b500::/32', '2405:8100::/32', '2a06:98c0::/29',
    '2c0f:f248::/32',
]

_NETWORKS = [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_RANGES]


def _from_cloudflare(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in network for network in _NETWORKS)


class CloudflareRealIPMiddleware:
    """Rewrite REMOTE_ADDR to the real client, but only behind Cloudflare."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        remote = request.META.get('REMOTE_ADDR', '')
        forwarded = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
        if forwarded and _from_cloudflare(remote):
            try:
                ipaddress.ip_address(forwarded)
            except ValueError:
                # A malformed header from the edge: leave REMOTE_ADDR alone
                # rather than throttling everyone into one bogus bucket.
                logger.warning('Bad CF-Connecting-IP: %r', forwarded)
            else:
                request.META['REMOTE_ADDR'] = forwarded
        return self.get_response(request)
