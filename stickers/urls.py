from django.urls import path

from . import views

app_name = 'stickers'

urlpatterns = [
    path('', views.sheet, name='sheet'),
    path('submit/', views.submit, name='submit'),
    path('submit/thanks/', views.submitted, name='submitted'),
    path('species/<slug:slug>/', views.species, name='species'),
    path('sticker/<slug:slug>/', views.detail, name='detail'),
]
