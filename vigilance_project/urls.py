"""
URL configuration for vigilance_project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

admin.site.site_header = "Vigilance - Contrôle & Collecte Documentaire"
admin.site.site_title = "Vigilance Admin"
admin.site.index_title = "Gestion du Devoir de Vigilance"

urlpatterns = [
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    path('admin/', admin.site.urls),
    path('', include('vigilance_core.urls')),
]
