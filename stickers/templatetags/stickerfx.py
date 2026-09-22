"""Small display helpers for the sheet."""

from django import template

register = template.Library()

# A real sticker sheet is never perfectly aligned. Derive a stable tilt from
# the pk so a given sticker always sits at the same angle (no re-flow on
# reload, and no random() in a template).
TILTS = [-3.5, 2.5, -1.5, 3.0, -2.0, 1.0, -3.0, 2.0, -1.0, 3.5, -2.5, 1.5]


@register.filter
def tilt(pk):
    try:
        return TILTS[int(pk) % len(TILTS)]
    except (TypeError, ValueError):
        return 0


@register.filter
def dictkey(mapping, key):
    """`{{ some_dict|dictkey:variable }}` — Django has no builtin for this."""
    try:
        return mapping.get(key, key)
    except AttributeError:
        return key
