from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect as _redirect
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from django.templatetags.static import static

from . import shapes
from .forms import ReframeForm, SubmitStickerForm
from .models import Species, Sticker


def _published():
    return (Sticker.objects
            .filter(status=Sticker.Status.PUBLISHED)
            .select_related('species'))


def sheet(request):
    """The gallery: every published sticker, laid out as one big sticker sheet."""
    stickers = _published()

    group = request.GET.get('group') or ''
    query = (request.GET.get('q') or '').strip()
    if group:
        stickers = stickers.filter(species__group=group)
    if query:
        stickers = stickers.filter(
            Q(species__common_name__icontains=query)
            | Q(species__scientific_name__icontains=query)
            | Q(caption__icontains=query)
            | Q(location__icontains=query)
            | Q(wildlife_investigator__icontains=query))

    # The chips are hidden (STICKER_SHEET_SHOW_FILTERS), so don't pay for the
    # aggregate on every page load. When it comes back: these joins bypass
    # Sticker's soft-delete manager, so the deleted_at condition has to be
    # spelled out or the counts include stickers that are in the bin.
    groups = []
    if settings.STICKER_SHEET_SHOW_FILTERS:
        live_published = Q(stickers__status=Sticker.Status.PUBLISHED,
                           stickers__deleted_at__isnull=True)
        groups = (Species.objects
                  .filter(live_published)
                  .values('group')
                  .annotate(n=Count('stickers', filter=live_published))
                  .order_by('-n'))

    return render(request, 'stickers/sheet.html', {
        'nav': 'gallery',
        'show_filters': settings.STICKER_SHEET_SHOW_FILTERS,
        'stickers': stickers,
        'groups': groups,
        'group_labels': dict(Species.Group.choices),
        'active_group': group,
        'query': query,
    })


def detail(request, slug):
    sticker = get_object_or_404(_published(), slug=slug)
    more = (_published()
            .filter(species=sticker.species)
            .exclude(pk=sticker.pk)[:8])
    return render(request, 'stickers/detail.html', {
        'nav': 'gallery',
        'show_filters': settings.STICKER_SHEET_SHOW_FILTERS,
        'sticker': sticker,
        'more': more,
    })


def species(request, slug):
    species_obj = get_object_or_404(Species, slug=slug)
    return render(request, 'stickers/species.html', {
        'nav': 'gallery',
        'show_filters': settings.STICKER_SHEET_SHOW_FILTERS,
        'species': species_obj,
        'stickers': _published().filter(species=species_obj),
    })


def submit(request):
    if request.method == 'POST':
        form = SubmitStickerForm(request.POST, request.FILES)
        if form.is_valid():
            sticker = form.save()

            # The form always writes PENDING — that invariant is the whole
            # reason an open upload form is safe, and it is not relaxed here.
            # Staff are promoted afterwards, explicitly, by the view: someone
            # who can already publish from the admin gains nothing by being
            # made to wait for themselves.
            if request.user.is_authenticated and request.user.is_staff:
                sticker.status = Sticker.Status.PUBLISHED
                sticker.save(update_fields=['status', 'updated_at'])
                messages.success(request, 'Published — it is on the sheet.')
                return redirect('stickers:detail', slug=sticker.slug)

            messages.success(
                request,
                'Got it. Your sticker is in the queue — once it is reviewed '
                'it will appear on the sheet.')
            return redirect('stickers:submitted')
    else:
        form = SubmitStickerForm()

    return render(request, 'stickers/submit.html',
                  {'form': form, 'palette': _palette()})


def submitted(request):
    return render(request, 'stickers/submitted.html')


# --- staff review ----------------------------------------------------------
# The Django admin is fine for metadata, but framing is a visual decision —
# you cannot judge a crop from four numbers in a form. These two pages wrap
# the same editor the submit form uses.

def _palette():
    return [{
        'slug': slug,
        'label': label,
        'outline': static('stickers/shapes/%s.outline.png' % slug),
        'mask': static('stickers/shapes/%s.mask.png' % slug),
        'swatch': static('stickers/shapes/%s.svg' % slug),
    } for slug, label in shapes.available()]


@staff_member_required
def review(request):
    """The moderation queue: pending first, with publish/reject in one click."""
    if request.method == 'POST':
        pk = request.POST.get('pk')
        action = request.POST.get('action')
        sticker = Sticker.all_objects.filter(pk=pk).first()
        if sticker and action in ('publish', 'reject', 'bin', 'restore'):
            if action == 'publish':
                sticker.status = Sticker.Status.PUBLISHED
                sticker.save(update_fields=['status', 'updated_at'])
                messages.success(request, '%s is on the sheet.' % sticker.species)
            elif action == 'reject':
                sticker.status = Sticker.Status.REJECTED
                sticker.save(update_fields=['status', 'updated_at'])
                messages.success(request, '%s rejected.' % sticker.species)
            elif action == 'bin':
                # Soft delete — the upload is the only copy and is kept.
                sticker.delete()
                messages.success(request, '%s moved to the bin.' % sticker.species)
            else:
                sticker.restore()
                messages.success(request, '%s restored.' % sticker.species)
        return _redirect('stickers:review')

    show = request.GET.get('show') or 'pending'
    qs = Sticker.all_objects.select_related('species')
    if show == 'bin':
        qs = qs.filter(deleted_at__isnull=False)
    else:
        qs = qs.filter(deleted_at__isnull=True, status=show) \
            if show in dict(Sticker.Status.choices) else qs.filter(
                deleted_at__isnull=True, status=Sticker.Status.PENDING)

    counts = {
        'pending': Sticker.objects.filter(status=Sticker.Status.PENDING).count(),
        'published': Sticker.objects.filter(status=Sticker.Status.PUBLISHED).count(),
        'rejected': Sticker.objects.filter(status=Sticker.Status.REJECTED).count(),
        'bin': Sticker.all_objects.filter(deleted_at__isnull=False).count(),
    }
    return render(request, 'stickers/review.html', {
        'nav': 'gallery', 'stickers': qs, 'show': show, 'counts': counts,
    })


@staff_member_required
def reframe(request, slug):
    """Re-cut one sticker: pick a different outline, pan and zoom."""
    sticker = get_object_or_404(Sticker.all_objects, slug=slug)

    if request.method == 'POST':
        form = ReframeForm(request.POST, instance=sticker)
        if form.is_valid():
            # Saving with any framing field changed re-cuts the derivatives;
            # see Sticker.save().
            form.save()
            if request.POST.get('and_publish'):
                sticker.status = Sticker.Status.PUBLISHED
                sticker.save(update_fields=['status', 'updated_at'])
                messages.success(request, 'Re-cut and published.')
            else:
                messages.success(request, 'Re-cut.')
            return _redirect('stickers:reframe', slug=sticker.slug)
    else:
        form = ReframeForm(instance=sticker)

    return render(request, 'stickers/reframe.html', {
        'nav': 'gallery',
        'sticker': sticker,
        'form': form,
        'palette': _palette(),
        # Frame the clip itself, playing. A subject moves, so a single frame
        # is a poor thing to judge a crop by — and the poster shares the
        # video's dimensions, so the resulting crop is identical either way.
        #
        # The poster is passed as a fallback because not every browser can
        # decode every container (Firefox will not touch .mov), and a stage
        # that silently stays blank is worse than a still.
        'existing_url': sticker.media.url if sticker.media else '',
        'existing_kind': 'video' if sticker.is_video else 'image',
        'existing_poster': sticker.poster_url if sticker.is_video else '',
    })


def sticker_sheet(request):
    """
    A playground: every published sticker in a tray, and a canvas to arrange
    them on. Deliberately unlinked from the site's navigation.

    Nothing is saved server-side — the arrangement is one person messing
    about, not content. It survives a reload via localStorage and goes no
    further.
    """
    stickers = [s for s in _published().order_by('species__common_name')
                if s.sticker_url]
    return render(request, 'stickers/sticker_sheet.html', {
        'stickers': stickers,
        'nav': '',
    })
