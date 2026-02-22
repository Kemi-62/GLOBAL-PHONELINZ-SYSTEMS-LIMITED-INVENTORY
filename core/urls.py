from django.urls import path
from . import views

urlpatterns = [
    path('', views.custom_login, name='login'),
    path('staff/', views.staff_dashboard, name='staff_dashboard'),
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('director/', views.director_dashboard, name='director_dashboard'),
    path('approve/<int:activity_id>/', views.approve_activity, name='approve_activity'),
]
