from django.urls import path
from . import views

urlpatterns = [
    path('depot/<str:token>/', views.public_deposit, name='public_deposit'),
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
]
