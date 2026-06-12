from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.custom_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('accounts/login/', views.custom_login, name='account_login'),

    # Password Reset (Django built-in)
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),

    # Dashboards
    path('staff/', views.staff_dashboard, name='staff_dashboard'),
    path('telecom/', views.staff_dashboard, name='telecom_dashboard'),
    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('director/', views.director_dashboard, name='director_dashboard'),
    path('retail/', views.retail_dashboard, name='retail_dashboard'),
    path('multichoice/', views.multichoice_dashboard, name='multichoice_dashboard'),

    # Sales
    path('record-sale/', views.record_retail_sale, name='record_retail_sale'),
    path('record-multichoice/', views.record_multichoice_sale, name='record_multichoice_sale'),
    path('void-sale/<int:sale_id>/', views.void_sale, name='void_sale'),
    path('manager/sales-today/', views.manager_sales_today, name='manager_sales_today'),

    # MultiChoice
    path('multichoice/start-week/', views.start_weekly_report, name='start_weekly_report'),
    path('multichoice/close-week/', views.close_weekly_report, name='close_weekly_report'),
    path('record-balance/', views.record_balance, name='record_balance'),
    path('record-daily-balance/', views.record_daily_balance, name='record_daily_balance'),
    path('my-commissions/', views.my_commissions, name='my_commissions'),

    # Stock
    path('add-stock-safe/', views.add_stock_to_safe, name='add_stock_to_safe'),
    path('release-stock/', views.release_stock, name='release_stock'),
    path('approve-stock-request/<int:request_id>/', views.approve_stock_request, name='approve_stock_request'),
    path('request-stock/', views.request_stock, name='request_stock'),
    path('stock-log/', views.stock_movement_log, name='stock_movement_log'),
    path('stock-alerts/', views.stock_alerts, name='stock_alerts'),
    path('upload-retail-csv/', views.upload_retail_csv, name='upload_retail_csv'),
    path('upload-manager-csv/', views.upload_manager_csv, name='upload_manager_csv'),
    path('upload-director-csv/', views.upload_director_csv, name='upload_director_csv'),
    path('upload-stock-csv/', views.upload_stock_csv, name='upload_stock_csv'),

    # Director Safe
    path('director/safe/', views.director_safe_stock, name='director_safe_stock'),
    path('director/safe/add/', views.add_director_stock, name='add_director_stock'),
    path('director/safe/delete/<int:stock_id>/', views.delete_director_stock, name='delete_director_stock'),
    path('director/safe/release/', views.director_release_stock, name='director_release_stock'),
    path('director/safe/create-product/', views.create_director_product, name='create_director_product'),
    path('edit-director-stock/<int:stock_id>/', views.edit_director_stock, name='edit_director_stock'),

    # Director reports & tools
    path('daily-sales-report/', views.daily_sales_report, name='daily_sales_report'),
    path('director/all-stock/', views.director_all_branch_stock, name='director_all_branch_stock'),
    path('director/all-activities/', views.director_all_activities, name='director_all_activities'),
    path('director/payroll-summary/', views.payroll_deduction_summary, name='payroll_deduction_summary'),
    path('director/audit-log/', views.audit_log_view, name='audit_log_view'),
    path('branch-report-pdf/<int:branch_id>/', views.generate_branch_report_pdf, name='generate_branch_report_pdf'),
    path('export-report/', views.export_branch_report, name='export_branch_report'),
    path('attendance/export-pdf/', views.export_monthly_attendance_pdf, name='export_monthly_attendance_pdf'),

    # Retail
    path('staff-create-product/', views.staff_create_product, name='staff_create_product'),
    path('product-catalog/', views.product_catalog, name='product_catalog'),
    path('edit-staff-stock-price/<int:stock_id>/', views.edit_staff_stock_price, name='edit_staff_stock_price'),
    path('edit-staff-stock-quantity/<int:stock_id>/', views.edit_staff_stock_quantity, name='edit_staff_stock_quantity'),
    path('edit-product-price/<int:product_id>/', views.edit_product_price, name='edit_product_price'),

    # Telecom
    path('manager/create-target/', views.create_service_target, name='create_service_target'),
    path('staff-monthly-activity/', views.staff_monthly_activity, name='staff_monthly_activity'),
    path('approve/<int:activity_id>/', views.approve_activity, name='approve_activity'),
    path('record-physical-product/', views.record_physical_product, name='record_physical_product'),
    path('add-sim-received/', views.add_sim_received, name='add_sim_received'),
    path('set-sim-opening-balance/', views.set_sim_opening_balance, name='set_sim_opening_balance'),

    # Attendance
    path('attendance/', views.check_in, name='check_in'),
    path('check-out/', views.check_out, name='check_out'),
    path('attendance/history/', views.attendance_history, name='attendance_history'),
    path('director/attendance/', views.director_attendance_dashboard, name='director_attendance_dashboard'),
    path('director/manage-locations/', views.manage_branch_locations, name='manage_branch_locations'),

    # Staff movement
    path('staff-checkout/<int:staff_id>/', views.staff_checkout, name='staff_checkout'),
    path('staff-checkin/<int:staff_id>/', views.staff_checkin, name='staff_checkin'),

    # Expenses & misc
    path('record-expense/', views.record_expense, name='record_expense'),
    path('add-category/', views.add_category, name='add_category'),

    # CRM
    path('customer-crm/', views.customer_crm, name='customer_crm'),
    path('customer/<int:customer_id>/history/', views.customer_history, name='customer_history'),

    # Commissions
    path('add-device-commission/', views.add_device_commission, name='add_device_commission'),
    path('commission-tracking/', views.commission_tracking, name='commission_tracking'),

    # Suppliers & Purchase Orders
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('purchase-orders/', views.purchase_order_list, name='purchase_order_list'),
    path('purchase-orders/create/', views.purchase_order_create, name='purchase_order_create'),
    path('purchase-orders/<int:po_id>/receive/', views.purchase_order_receive, name='purchase_order_receive'),

    # Notifications
    path('notifications/', views.notifications_view, name='notifications_view'),
    path('notifications/count/', views.notification_count, name='notification_count'),
    path('multichoice/export-pdf/', views.multichoice_export_pdf, name='multichoice_export_pdf'),
    path('retail/sales-history/', views.retail_sales_history, name='retail_sales_history'),
    path('telecom/activity-history/', views.telecom_activity_history, name='telecom_activity_history'),
    path('invoice/<str:sale_type>/<int:sale_id>/', views.invoice_preview, name='invoice_preview'),
    path('invoice/<str:sale_type>/<int:sale_id>/pdf/', views.invoice_download_pdf, name='invoice_download_pdf'),
    path('invoice/<str:sale_type>/<int:sale_id>/receipt/', views.invoice_receipt, name='invoice_receipt'),
    path('wholesale/', views.wholesale_catalog, name='wholesale_catalog'),
    path('wholesale/add-device/', views.wholesale_add_device, name='wholesale_add_device'),
    path('wholesale/record-sale/', views.wholesale_record_sale, name='wholesale_record_sale'),
    path('director/multichoice-balance/', views.director_multichoice_balance, name='director_multichoice_balance'),

    # Moniepoint POS
    path('moniepoint/record/', views.record_moniepoint, name='record_moniepoint'),
    path('director/moniepoint-reconcile/', views.moniepoint_reconcile, name='moniepoint_reconcile'),

    # Loyalty
    path('loyalty/customer/<str:phone>/', views.loyalty_customer_lookup, name='loyalty_customer_lookup'),
    path('loyalty/redeem/', views.loyalty_redeem, name='loyalty_redeem'),

    # Change Log
    path('director/change-log/', views.change_log_view, name='change_log_view'),

    # Backup
    path('director/backups/', views.backup_history_view, name='backup_history_view'),
    path('director/backups/trigger/', views.trigger_backup, name='trigger_backup'),

    # Price Floor
    path('director/price-floors/', views.manage_price_floors, name='manage_price_floors'),
]
