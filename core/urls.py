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
    path('record-multichoice/', views.record_multichoice_sale, name='record_multichoice_sale'),
    path('multichoice/start-week/', views.start_weekly_report, name='start_weekly_report'),
    path('multichoice/close-week/', views.close_weekly_report, name='close_weekly_report'),
    path('staff-create-product/', views.staff_create_product, name='staff_create_product'),
    path('add-category/', views.add_category, name='add_category'),
    path('record-expense/', views.record_expense, name='record_expense'),
    path('request-stock/', views.request_stock, name='request_stock'),
    path('approve-stock-request/<int:request_id>/', views.approve_stock_request, name='approve_stock_request'),
    path('branch-report-pdf/<int:branch_id>/', views.generate_branch_report_pdf, name='generate_branch_report_pdf'),
]
