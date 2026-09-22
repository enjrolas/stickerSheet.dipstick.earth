from django.urls import path

from . import views

app_name = 'pages'

urlpatterns = [
    path('', views.Index.as_view(), name='index'),
    path('contacts/', views.Contacts.as_view(), name='contacts'),
    path('kickstarter/', views.Kickstarter.as_view(), name='kickstarter'),
]
