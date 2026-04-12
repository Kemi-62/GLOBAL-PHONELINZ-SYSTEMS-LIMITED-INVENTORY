from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, Q
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity, BranchSafeStock, StockMovement, Product, StaffStock, RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory, MultiChoiceSale, MultiChoiceWeeklyReport, MultiChoiceBalance, Expense, StockRequest, Attendance, DirectorSafeStock, SimInventory, SimInventoryLog, CommissionPayment
from .utils.decorators import role_required

def custom_login(request):
    return render(request, 'login.html')

def user_logout(request):
    logout(request)
    return redirect('login')

def csrf_failure(request, reason=''):
    return HttpResponseForbidden('CSRF verification failed.')

def admin_redirect(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_superuser:
        from django.contrib.admin.sites import site as admin_site
        return admin_site.index(request)
    if hasattr(request.user, 'role') and request.user.role:
        if request.user.role == 'DIRECTOR':
            return redirect('director_dashboard')
        if request.user.role == 'MANAGER':
            return redirect('manager_dashboard')
        if request.user.role == 'RETAIL':
            return redirect('retail_dashboard')
        if request.user.role == 'MULTICHOICE':
            return redirect('multichoice_dashboard')
        if request.user.role == 'TELECOM':
            return redirect('staff_dashboard')
    return redirect('login')

def staff_dashboard(request):
    return redirect('multichoice_dashboard')

def manager_dashboard(request):
    return HttpResponse('manager dashboard')

def director_dashboard(request):
    return HttpResponse('director dashboard')

def retail_dashboard(request):
    return HttpResponse('retail dashboard')

def daily_sales_report(request):
    return HttpResponse('daily sales report')

def staff_monthly_activity(request):
    return HttpResponse('staff monthly activity')

def create_service_target(request):
    return redirect('manager_dashboard')

def approve_activity(request, activity_id):
    return redirect('manager_dashboard')

def add_stock_to_safe(request):
    return redirect('manager_dashboard')

def release_stock(request):
    return redirect('manager_dashboard')

def record_retail_sale(request):
    return redirect('retail_dashboard')

def record_multichoice_sale(request):
    if request.method == 'POST':
        customer_name = request.POST.get('customer_name')
        customer_phone = request.POST.get('customer_phone')
        iuc_number = request.POST.get('iuc_number')
        service_type = request.POST.get('service_type')
        package_type = request.POST.get('package_type')
        transaction_type = request.POST.get('transaction_type')
        cost_price = Decimal(request.POST.get('cost_price', 0) or 0)
        amount = Decimal(request.POST.get('amount', 0) or 0)
        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(staff=request.user, branch=request.user.branch, week_start_date=(timezone.now().date() - timedelta(days=timezone.now().weekday())))
        previous_balance = MultiChoiceBalance.objects.filter(weekly_report=weekly_report).order_by('-date', '-time').first()
        starting_balance = previous_balance.balance_after_sale if previous_balance and previous_balance.balance_after_sale is not None else weekly_report.opening_balance + weekly_report.additional_funds
        balance_after_sale = starting_balance - cost_price
        MultiChoiceSale.objects.create(staff=request.user, branch=request.user.branch, customer_name=customer_name, customer_phone=customer_phone, iuc_number=iuc_number, service_type=service_type, package_type=package_type, transaction_type=transaction_type, cost_price=cost_price, amount=amount)
        MultiChoiceBalance.objects.create(weekly_report=weekly_report, balance_amount=starting_balance, balance_after_sale=balance_after_sale, sale_cost_price=cost_price, notes=f'Subscription recorded: {package_type}')
        weekly_report.total_subscriptions = (weekly_report.total_subscriptions or 0) + amount
        weekly_report.save(update_fields=['total_subscriptions'])
    return redirect('multichoice_dashboard')

def start_weekly_report(request):
    return redirect('multichoice_dashboard')

def close_weekly_report(request):
    return redirect('multichoice_dashboard')

def staff_create_product(request):
    return redirect('retail_dashboard')

def add_category(request):
    return redirect('manager_dashboard')

def record_expense(request):
    return redirect('manager_dashboard')

def request_stock(request):
    return redirect('manager_dashboard')

def approve_stock_request(request, request_id):
    return redirect('manager_dashboard')

def generate_branch_report_pdf(request, branch_id):
    return HttpResponse('pdf')

def export_branch_report(request):
    return HttpResponse('export')

def check_in(request):
    return HttpResponse('check in')

def attendance_history(request):
    return HttpResponse('attendance history')

def director_attendance_dashboard(request):
    return HttpResponse('director attendance')

def manage_branch_locations(request):
    return HttpResponse('manage locations')

def director_safe_stock(request):
    return HttpResponse('safe stock')

def add_director_stock(request):
    return redirect('director_safe_stock')

def delete_director_stock(request, stock_id):
    return redirect('director_safe_stock')

def edit_director_stock(request, stock_id):
    return redirect('director_safe_stock')

def create_director_product(request):
    return redirect('director_safe_stock')

def product_catalog(request):
    return HttpResponse('product catalog')

def record_physical_product(request):
    return redirect('manager_dashboard')

def export_monthly_attendance_pdf(request):
    return HttpResponse('attendance pdf')

def record_balance(request):
    return redirect('multichoice_dashboard')

def upload_stock_csv(request):
    return redirect('director_dashboard')

def customer_crm(request):
    return HttpResponse('crm')

def stock_alerts(request):
    return HttpResponse('alerts')

def staff_checkout(request, staff_id):
    return redirect('manager_dashboard')

def staff_checkin(request, staff_id):
    return redirect('manager_dashboard')

def add_device_commission(request):
    return redirect('manager_dashboard')

def record_daily_balance(request):
    return redirect('multichoice_dashboard')

def commission_tracking(request):
    return HttpResponse('commission tracking')

def my_commissions(request):
    if request.user.role != 'MULTICHOICE':
        return HttpResponseForbidden('Not allowed')
    commissions = CommissionPayment.objects.filter(staff=request.user).order_by('-date_detected')
    total_earned = commissions.aggregate(total=Sum('commission_detected'))['total'] or 0
    return render(request, 'my_commissions.html', {'commissions': commissions, 'total_earned': total_earned})

def edit_staff_stock_price(request, stock_id):
    return redirect('retail_dashboard')

def edit_product_price(request, product_id):
    return redirect('retail_dashboard')

def add_sim_received(request):
    return redirect('manager_dashboard')

def set_sim_opening_balance(request):
    return redirect('manager_dashboard')
