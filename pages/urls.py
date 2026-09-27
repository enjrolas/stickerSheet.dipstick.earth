from django.urls import path
from django.views.generic import RedirectView

from . import views

# The campaign is live, so /kickstarter/ goes straight to it. The local page
# said "coming soon" and would now contradict the home page's own button.
# A temporary redirect, not permanent: a campaign ends, and a 301 would be
# cached in people's browsers long after there is anywhere to send them.
KICKSTARTER = 'https://www.kickstarter.com/projects/ex-invention/the-dipstick'

app_name = 'pages'

urlpatterns = [
    path('', views.Index.as_view(), name='index'),
    path('contacts/', views.Contacts.as_view(), name='contacts'),
    path('kickstarter/',
         RedirectView.as_view(url=KICKSTARTER, permanent=False),
         name='kickstarter'),
]
