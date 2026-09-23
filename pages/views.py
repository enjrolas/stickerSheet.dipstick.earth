"""
The marketing pages, which used to be standalone HTML files served straight
off disk at dipstick.earth.

They are templates now so the navbar and footer exist in exactly one place.
Nothing here touches the database — they are static content rendered through
Django purely to share the chrome.
"""

from django.views.generic import TemplateView

from stickers.models import Sticker


class Page(TemplateView):
    """A marketing page. `nav` highlights the matching navbar entry."""

    nav = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nav'] = self.nav
        return context


class Index(Page):
    template_name = 'pages/index.html'
    nav = 'index'

    def get_context_data(self, **kwargs):
        """
        The "what you can see" carousel is fed from the gallery rather
        than a fixed list of files. There was only ever one piece of real
        footage in assets/ (the jellyfish) — everything else in the old
        carousel shows the device being used, not what it saw. Drawing
        from published stickers means the section is about the right
        thing, and it fills itself as people send more in.
        """
        context = super().get_context_data(**kwargs)
        context['sightings'] = (Sticker.objects
                                .filter(status=Sticker.Status.PUBLISHED)
                                .select_related('species')[:8])
        return context


class Contacts(Page):
    template_name = 'pages/contacts.html'
    nav = 'contacts'


class Kickstarter(Page):
    template_name = 'pages/kickstarter.html'
    nav = 'kickstarter'
