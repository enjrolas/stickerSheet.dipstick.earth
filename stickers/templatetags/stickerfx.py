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


# Hand-placed slots for the "what you can see" panel. Scattered rather than
# gridded, but not actually random: a random layout re-rolls on every render,
# so a sticker would jump between page loads and could land on the Dipper
# Keeper's logo or half off the edge.
#
# Every slot sits BELOW THE FOLD — the purple flap ends 26.9% down the
# artwork (measured, not guessed), and a sticker over it would look stuck to
# the lid rather than the folder. 32% is the first safe row.
#
# left %, top %, width %, rotation deg
SCATTER = [
    (6,  33, 23, -17),
    (34, 31, 15,  13),
    (54, 35, 27,  -6),
    (82, 32, 14,  22),
    (13, 57, 29,   8),
    (47, 60, 18, -24),
    (69, 55, 22,  15),
    (87, 64, 12, -11),
    (27, 74, 20,  19),
    (60, 80, 16, -15),
]


@register.filter
def scatter(index):
    """Inline style placing sticker `index` on the keeper."""
    left, top, width, rot = SCATTER[int(index) % len(SCATTER)]
    return ('left:%d%%; top:%d%%; width:%d%%; --tilt:%ddeg'
            % (left, top, width, rot))
