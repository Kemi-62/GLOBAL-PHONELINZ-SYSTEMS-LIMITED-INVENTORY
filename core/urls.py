from django.urls import path
from . import views

urlpatterns = [
    path('', views.custom_login, name='login'),
    path('staff/', views.staff_dashboard, name='staff_dashboard'),
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('director/', views.director_dashboard, name='director_dashboard'),
    path('retail/', views.retail_dashboard, name='retail_dashboard'),
    path('multichoice/', views.multichoice_dashboard, name='multichoice_dashboard'),
    path('approve/<int:activity_id>/', views.approve_activity, name='approve_activity'),
    path('add-stock-safe/', views.add_stock_to_safe, name='add_stock_to_safe'),
    path('release-stock/', views.release_stock, name='release_stock'),
    path('record-sale/', views.record_retail_sale, name='record_retail_sale'),
]
