"""
The marketing pages, which used to be standalone HTML files served straight
off disk at dipstick.earth.

They are templates now so the navbar and footer exist in exactly one place.
Nothing here touches the database — they are static content rendered through
Django purely to share the chrome.
"""

from django.views.generic import TemplateView


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


class Contacts(Page):
    template_name = 'pages/contacts.html'
    nav = 'contacts'


class Kickstarter(Page):
    template_name = 'pages/kickstarter.html'
    nav = 'kickstarter'
