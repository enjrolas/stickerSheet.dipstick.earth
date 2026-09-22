from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import SubmitStickerForm
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

    groups = (Species.objects
              .filter(stickers__status=Sticker.Status.PUBLISHED)
              .values('group')
              .annotate(n=Count('stickers'))
              .order_by('-n'))

    return render(request, 'stickers/sheet.html', {
        'stickers': stickers,
        'groups': groups,
        'group_labels': dict(Species.Group.choices),
        'active_group': group,
        'query': query,
        'total': _published().count(),
        'species_total': Species.objects.filter(
            stickers__status=Sticker.Status.PUBLISHED).distinct().count(),
    })


def detail(request, slug):
    sticker = get_object_or_404(_published(), slug=slug)
    more = (_published()
            .filter(species=sticker.species)
            .exclude(pk=sticker.pk)[:8])
    return render(request, 'stickers/detail.html',
                  {'sticker': sticker, 'more': more})


def species(request, slug):
    species_obj = get_object_or_404(Species, slug=slug)
    return render(request, 'stickers/species.html', {
        'species': species_obj,
        'stickers': _published().filter(species=species_obj),
    })


def submit(request):
    if request.method == 'POST':
        form = SubmitStickerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Got it. Your sticker is in the queue — once it is reviewed '
                'it will appear on the sheet.')
            return redirect('stickers:submitted')
    else:
        form = SubmitStickerForm()
    return render(request, 'stickers/submit.html', {'form': form})


def submitted(request):
    return render(request, 'stickers/submitted.html')
