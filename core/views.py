from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.contrib.auth.decorators import login_required
from datetime import date, time
import math
from django.db.models import Sum, F
from django.utils import timezone
from decimal import Decimal
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity, BranchSafeStock, StockMovement, Product, StaffStock, RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory, MultiChoiceSale, MultiChoiceWeeklyReport, MultiChoiceBalance, Expense, StockRequest, Attendance, DirectorSafeStock
from .utils.decorators import role_required

# -----------------------
# Admin Redirect (Non-Superadmin Protection)
# -----------------------
def admin_redirect(request):
    """Redirect non-superadmin users from /admin/ to their dashboard"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    if request.user.is_superuser:
        from django.contrib.admin.sites import site as admin_site
        return admin_site.index(request)
    
    # Redirect to appropriate dashboard based on role
    if hasattr(request.user, 'role') and request.user.role:
        if request.user.role == "DIRECTOR":
            return redirect("director_dashboard")
        elif request.user.role == "MANAGER":
            return redirect("manager_dashboard")
        elif request.user.role == "RETAIL":
            return redirect("retail_dashboard")
        elif request.user.role == "MULTICHOICE":
            return redirect("multichoice_dashboard")
        elif request.user.role == "TELECOM":
            return redirect("staff_dashboard")
    
    return redirect("director_dashboard")

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def attendance_status():
    now = timezone.localtime()
    current_time = now.time()
    weekday = now.weekday()
    if weekday < 5:
        if time(7,30) <= current_time <= time(8,0):
            return "ontime"
        elif time(8,1) <= current_time <= time(8,59):
            return "late"
        elif current_time >= time(9,0):
            return "absent"
    if weekday == 5:
        if time(9,0) <= current_time <= time(9,15):
            return "ontime"
        elif current_time > time(9,15):
            return "late"
    return "early"

# -----------------------
# Custom Login
# -----------------------
def custom_login(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('admin:index')
        if hasattr(request.user, 'role') and request.user.role:
            if request.user.role == "DIRECTOR":
                return redirect("director_dashboard")
            elif request.user.role == "MANAGER":
                return redirect("manager_dashboard")
            elif request.user.role == "RETAIL":
                return redirect("retail_dashboard")
            elif request.user.role == "MULTICHOICE":
                return redirect("multichoice_dashboard")
            elif request.user.role == "TELECOM":
                return redirect("staff_dashboard")
        return redirect("director_dashboard")
        
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, "Username and password required")
            return render(request, 'login.html')

        user_auth = authenticate(request, username=username, password=password)

        if user_auth is not None:
            login(request, user_auth)
            messages.success(request, f"Welcome, {username}!")

            if user_auth.is_superuser:
                return redirect('director_dashboard')

            role = getattr(user_auth, 'role', None)
            if role == "TELECOM":
                return redirect("staff_dashboard")
            elif role == "RETAIL":
                return redirect("retail_dashboard")
            elif role == "MULTICHOICE":
                return redirect("multichoice_dashboard")
            elif role == "MANAGER":
                return redirect("manager_dashboard")
            elif role == "DIRECTOR":
                return redirect("director_dashboard")
            else:
                return redirect('director_dashboard')
        else:
            messages.error(request, "Invalid username or password")
            return render(request, 'login.html')

    return render(request, 'login.html')

def user_logout(request):
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, "Logged out successfully")
    return redirect('login')

def csrf_failure(request, reason=""):
    messages.error(request, "Your session expired or was interrupted. Please try again.")
    return redirect('login')

# -----------------------
# Staff Dashboard
# -----------------------
@login_required
def staff_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'TELECOM':
        return HttpResponseForbidden("Not allowed")

    today = date.today()

    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date__year=today.year,
        date__month=today.month
    )

    activities = ServiceActivity.objects.filter(
        staff=request.user,
        date__year=today.year,
        date__month=today.month
    )
    
    # Global Category Context for Sidebar
    categories = RetailCategory.objects.all()

    if request.method == "POST":
        service_type = request.POST.get("service_type")
        quantity = int(request.POST.get("quantity") or 0)
        device_tag_id = request.POST.get("device_tag")
        device_tag = None
        if device_tag_id:
            try:
                device_tag = DeviceTag.objects.get(id=device_tag_id)
            except DeviceTag.DoesNotExist:
                pass

        requires_approval = False
        if service_type == "SIM_REG":
            target = ServiceTarget.objects.filter(
                branch=request.user.branch,
                service_type="SIM_REG",
                device_tag=device_tag,
                date__year=today.year,
                date__month=today.month
            ).first()

            if target:
                achieved = ServiceActivity.objects.filter(
                    branch=request.user.branch,
                    service_type="SIM_REG",
                    device_tag=device_tag,
                    date__year=today.year,
                    date__month=today.month,
                    approved=True
                ).aggregate(total=Sum('quantity'))['total'] or 0

                if achieved >= target.target_number:
                    requires_approval = True

        ServiceActivity.objects.create(
            branch=request.user.branch,
            staff=request.user,
            service_type=service_type,
            device_tag=device_tag,
            quantity=quantity,
            requires_approval=requires_approval,
            approved=not requires_approval
        )
        return redirect("staff_dashboard")

    sim_targets = targets.filter(service_type="SIM_REG")
    device_progress = []

    for target in sim_targets:
        achieved = activities.filter(
            service_type="SIM_REG",
            device_tag=target.device_tag,
            approved=True
        ).aggregate(total=Sum("quantity"))["total"] or 0

        remaining = target.target_number - achieved

        percentage = 0
        if target.target_number > 0:
            percentage = (achieved / target.target_number) * 100

        device_progress.append({
            "device": target.device_tag.tag_name if target.device_tag else "Generic",
            "target": target.target_number,
            "achieved": achieved,
            "remaining": remaining if remaining > 0 else 0,
            "percentage": round(percentage, 2),
            "exceeded": achieved >= target.target_number
        })

    approved_activities = activities.filter(approved=True)
    pending_activities = activities.filter(approved=False, requires_approval=True)

    monthly_total = approved_activities.aggregate(
        total=Sum("quantity")
    )["total"] or 0

    from .models import CheckInOutLog
    check_logs = CheckInOutLog.objects.filter(staff=request.user).order_by('-date', '-check_in_time')[:20]
    
    context = {
        "device_progress": device_progress,
        "device_tags": DeviceTag.objects.filter(branch=request.user.branch),
        "activities": activities,
        "pending_activities": pending_activities,
        "monthly_total": monthly_total,
        "categories": categories,
        "check_logs": check_logs,
    }
    return render(request, "staff_dashboard.html", context)

# -----------------------
# Manager Dashboard
# -----------------------
from .utils.decorators import role_required

@role_required("MANAGER")
def manager_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'MANAGER':
        return HttpResponseForbidden("Not allowed")

    today = date.today()

    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date__year=today.year,
        date__month=today.month
    )

    activities = ServiceActivity.objects.filter(
        branch=request.user.branch,
        date__year=today.year,
        date__month=today.month
    )

    pending_approvals = ServiceActivity.objects.filter(
        branch=request.user.branch,
        requires_approval=True,
        approved=False
    )

    target_data = []
    for target in targets:
        total_achieved = activities.filter(
            service_type=target.service_type
        ).aggregate(total=Sum('quantity'))['total'] or 0

        remaining = target.target_number - total_achieved
        percentage = 0
        if target.target_number > 0:
            percentage = (total_achieved / target.target_number) * 100

        target_data.append({
            'service_type': target.service_type,
            'target_number': target.target_number,
            'achieved': total_achieved,
            'remaining': max(remaining, 0),
            'percentage': round(percentage, 2)
        })

    branch = request.user.branch
    today_date = timezone.now().date()

    # ---------------- STOCK MOVEMENTS ----------------
    today_movements = StockMovement.objects.filter(
        branch=branch,
        date=today_date
    )

    total_stock_out = today_movements.filter(
        movement_type="OUT"
    ).aggregate(total=Sum("quantity"))["total"] or 0

    # ---------------- MULTICHOICE DATA ----------------
    multichoice_today_qs = MultiChoiceSale.objects.filter(
        branch=branch,
        date=today_date
    )

    multichoice_revenue = multichoice_today_qs.aggregate(
        total=Sum("amount")
    )["total"] or 0

    # ---------------- RETAIL SALES TODAY ----------------
    product_filter = request.GET.get("product")
    staff_filter = request.GET.get("staff")

    retail_sales_today = RetailSale.objects.filter(
        branch=branch,
        date=today_date
    )

    if product_filter:
        retail_sales_today = retail_sales_today.filter(product_id=product_filter)

    if staff_filter:
        retail_sales_today = retail_sales_today.filter(staff_id=staff_filter)

    total_retail_quantity = retail_sales_today.aggregate(
        total=Sum("quantity")
    )["total"] or 0

    total_retail_revenue = retail_sales_today.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0

    # ---------------- SALES PER STAFF ----------------
    sales_per_staff = retail_sales_today.values(
        "staff__username"
    ).annotate(
        total_qty=Sum("quantity"),
        total_revenue=Sum(F("quantity") * F("selling_price"))
    )

    # ---------------- TOP PRODUCTS ----------------
    top_products = retail_sales_today.values(
        "product__model_name"
    ).annotate(
        total_qty=Sum("quantity")
    ).order_by("-total_qty")[:5]

    # ---------------- RETAIL DATA ----------------
    safe_stocks = BranchSafeStock.objects.filter(branch=branch)
    categories = RetailCategory.objects.all()
    retail_staff = User.objects.filter(branch=branch, role="RETAIL")
    
    pending_stock_requests = StockRequest.objects.filter(branch=branch, status="PENDING")
    expenses = Expense.objects.filter(branch=branch).order_by("-date")[:10]

    # Search and Filter logic for activities
    search_query = request.GET.get('search', '')
    if search_query:
        activities = activities.filter(staff__username__icontains=search_query)

    # Global Category Context for Sidebar
    categories = RetailCategory.objects.all()

    from .models import CheckInOutLog
    check_logs = CheckInOutLog.objects.filter(branch=request.user.branch).order_by('-date', '-check_in_time')[:20]

    context = {
        'target_data': target_data,
        'activities': activities,
        'pending_approvals': pending_approvals,
        "safe_stocks": safe_stocks,
        "categories": categories,
        "retail_staff": retail_staff,
        "today_movements": today_movements,
        "total_stock_out": total_stock_out,
        "multichoice_revenue": multichoice_revenue,
        "total_retail_quantity": total_retail_quantity,
        "total_retail_revenue": total_retail_revenue,
        "sales_per_staff": sales_per_staff,
        "top_products": top_products,
        "search_query": search_query,
        "pending_stock_requests": pending_stock_requests,
        "expenses": expenses,
        "check_logs": check_logs,
    }
    return render(request, "manager_dashboard.html", context)

@login_required
def approve_activity(request, activity_id):
    if not request.user.is_superuser and request.user.role != 'MANAGER':
        return HttpResponseForbidden("Not allowed")
    try:
        activity = ServiceActivity.objects.get(id=activity_id, branch=request.user.branch)
        activity.approved = True
        activity.requires_approval = False
        activity.save()
    except ServiceActivity.DoesNotExist:
        pass
    return redirect('manager_dashboard')

@role_required("RETAIL")
def retail_dashboard(request):
    from .models import CheckInOutLog
    from decimal import Decimal

    staff = request.user
    staff_stock = StaffStock.objects.filter(staff=staff).select_related('product')
    categories = RetailCategory.objects.all()
    check_logs = CheckInOutLog.objects.filter(staff=staff).order_by('-date', '-check_in_time')[:20]
    sales_history = RetailSale.objects.filter(staff=staff).select_related('product').order_by('-date', '-id')[:50]
    
    # Add total_revenue to each sale for display
    for sale in sales_history:
        sale.total_revenue = Decimal(sale.quantity) * sale.selling_price

    return render(request, "retail_dashboard.html", {
        "staff_stock": staff_stock,
        "categories": categories,
        "check_logs": check_logs,
        "sales_history": sales_history,
    })

@login_required
def record_retail_sale(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        staff = request.user
        branch = staff.branch

        product_id = request.POST.get("product")
        quantity = int(request.POST.get("quantity"))
        selling_price = float(request.POST.get("selling_price"))

        product = Product.objects.get(id=product_id)

        try:
            staff_stock = StaffStock.objects.get(
                staff=staff,
                product=product
            )
        except StaffStock.DoesNotExist:
            messages.error(request, "Insufficient stock.")
            return redirect("retail_dashboard")

        # Prevent selling more than available
        if quantity > staff_stock.quantity:
            messages.error(request, f"Insufficient stock. You only have {staff_stock.quantity} units.")
            return redirect("retail_dashboard")

        # Deduct stock
        staff_stock.quantity -= quantity
        staff_stock.save()

        # Create sale record
        RetailSale.objects.create(
            staff=staff,
            branch=branch,
            product=product,
            quantity=quantity,
            selling_price=selling_price,
            payment_method=request.POST.get("payment_method", "CASH")
        )
        messages.success(request, "Sale recorded successfully.")

    return redirect("retail_dashboard")

from datetime import date, timedelta
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity, BranchSafeStock, StockMovement, Product, StaffStock, RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory, MultiChoiceSale, MultiChoiceWeeklyReport

@role_required("MULTICHOICE")
def multichoice_dashboard(request):

    today = timezone.now().date()
    is_monday = today.weekday() == 0
    is_saturday = today.weekday() == 5
    
    # Get week start (Monday)
    week_start = today - timedelta(days=today.weekday())
    
    weekly_report = MultiChoiceWeeklyReport.objects.filter(
        staff=request.user,
        week_start_date=week_start
    ).first()

    today_sales = MultiChoiceSale.objects.filter(
        staff=request.user,
        date=today
    )

    total_today = today_sales.aggregate(total=Sum("amount"))["total"] or 0
    categories = RetailCategory.objects.all()

    # Calculate weekly total for closed reports
    weekly_total_sales = 0
    if weekly_report and weekly_report.is_closed:
        weekly_total_sales = weekly_report.total_subscriptions

    balance_history = None
    if weekly_report:
        balance_history = weekly_report.balance_history.all()
    
    from .models import CheckInOutLog
    check_logs = CheckInOutLog.objects.filter(staff=request.user).order_by('-date', '-check_in_time')[:20]

    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "total_today": total_today,
        "categories": categories,
        "weekly_report": weekly_report,
        "is_monday": is_monday,
        "is_saturday": is_saturday,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "check_logs": check_logs,
    })

@login_required
def start_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={
                'opening_balance': request.POST.get("opening_balance", 0),
                'additional_funds': request.POST.get("additional_funds", 0)
            }
        )
    return redirect("multichoice_dashboard")

@login_required
def close_weekly_report(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        report = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user,
            week_start_date=week_start
        ).first()
        
        if report and not report.is_closed:
            report.closing_balance = request.POST.get("closing_balance")
            
            # Calculate total subscriptions for the week
            week_total = MultiChoiceSale.objects.filter(
                staff=request.user,
                date__range=[week_start, today]
            ).aggregate(total=Sum("amount"))["total"] or 0
            
            report.total_subscriptions = week_total
            report.calculate_commission()
            report.is_closed = True
            report.save()
            messages.success(request, f"Week closed. Commission: ₦{report.commission}")
            
    return redirect("multichoice_dashboard")

@role_required("MULTICHOICE")
def record_balance(request):
    if request.method == 'POST':
        balance = request.POST.get('current_balance')
        notes = request.POST.get('notes', '')
        
        weekly_report = MultiChoiceWeeklyReport.objects.filter(
            staff=request.user, 
            branch=request.user.branch,
            is_closed=False
        ).first()
        
        if weekly_report and balance:
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=balance,
                notes=notes
            )
            messages.success(request, f"Balance ₦{balance} recorded successfully!")
        else:
            messages.error(request, "No active weekly report or invalid balance")
    
    return redirect('multichoice_dashboard')

@login_required
def record_expense(request):
    if request.method == "POST" and request.user.role == "MANAGER":
        Expense.objects.create(
            branch=request.user.branch,
            category=request.POST.get("category"),
            amount=request.POST.get("amount"),
            description=request.POST.get("description")
        )
        messages.success(request, "Expense recorded.")
    return redirect("manager_dashboard")

@login_required
def request_stock(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        StockRequest.objects.create(
            staff=request.user,
            branch=request.user.branch,
            product_name=request.POST.get("product_name"),
            quantity=request.POST.get("quantity")
        )
        messages.success(request, "Stock request submitted.")
    return redirect("retail_dashboard")

@login_required
def approve_stock_request(request, request_id):
    if request.user.role == "MANAGER":
        stock_req = StockRequest.objects.get(id=request_id, branch=request.user.branch)
        stock_req.status = "APPROVED"
        stock_req.save()
        messages.success(request, "Stock request approved.")
    return redirect("manager_dashboard")

from django.http import HttpResponse, HttpResponseForbidden
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
import io

from .utils.decorators import role_required

@role_required("MANAGER")
def export_branch_report(request):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Branch Daily Retail Report", styles["Title"]))
    elements.append(Spacer(1, 12))
    branch = request.user.branch
    today = timezone.now().date()
    sales = RetailSale.objects.filter(branch=branch, date=today)
    data = [["Product", "Quantity", "Amount"]]
    for sale in sales:
        data.append([sale.product.model_name, sale.quantity, str(sale.total_amount())])
    table = Table(data)
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf')

@login_required
def generate_branch_report_pdf(request, branch_id):
    if request.user.role not in ['DIRECTOR', 'MANAGER']:
        return HttpResponseForbidden("Not authorized")
    
    branch = Branch.objects.get(id=branch_id)
    today = date.today()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Report_{branch.name}_{today}.pdf"'
    
    p = canvas.Canvas(response, pagesize=letter)
    width, height = letter
    
    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, f"Daily Branch Report: {branch.name}")
    p.setFont("Helvetica", 12)
    p.drawString(100, height - 70, f"Date: {today}")
    
    # Telecom Summary
    activities = ServiceActivity.objects.filter(branch=branch, date=today)
    total_sim = activities.count()
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 110, "Telecom Performance")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 130, f"Total SIM Registrations: {total_sim}")
    
    # Retail Summary
    sales = RetailSale.objects.filter(branch=branch, date=today)
    total_qty = sales.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_rev = sales.aggregate(total=Sum(F('quantity') * F('selling_price')))['total'] or 0
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 170, "Retail Performance")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 190, f"Total Items Sold: {total_qty}")
    p.drawString(120, height - 210, f"Total Revenue: NGN {total_rev:,.2f}")
    
    # MultiChoice Summary
    mc_sales = MultiChoiceSale.objects.filter(branch=branch, date=today)
    mc_rev = mc_sales.aggregate(Sum('amount'))['amount__sum'] or 0
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 250, "MultiChoice Performance")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 270, f"Total Revenue: NGN {mc_rev:,.2f}")
    
    # Expenses
    exps = Expense.objects.filter(branch=branch, date=today)
    total_exp = exps.aggregate(Sum('amount'))['amount__sum'] or 0
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 310, "Expenses")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 330, f"Total Expenses: NGN {total_exp:,.2f}")
    
    # Net Profit
    # Note: Simplified profit calculation for PDF
    retail_profit = sales.aggregate(profit=Sum((F('selling_price') - F('product__cost_price')) * F('quantity')))['profit'] or 0
    net_profit = retail_profit - total_exp
    
    p.setFont("Helvetica-Bold", 14)
    p.drawString(100, height - 370, "Financial Summary")
    p.setFont("Helvetica", 12)
    p.drawString(120, height - 390, f"Gross Retail Profit: NGN {retail_profit:,.2f}")
    p.drawString(120, height - 410, f"Net Profit (Retail - Expenses): NGN {net_profit:,.2f}")
    
    p.showPage()
    p.save()
    return response

@login_required
def record_multichoice_sale(request):
    if request.method == "POST" and request.user.role == "MULTICHOICE":
        MultiChoiceSale.objects.create(
            staff=request.user,
            branch=request.user.branch,
            customer_name=request.POST.get("customer_name"),
            service_type=request.POST.get("service_type"),
            package_type=request.POST.get("package_type"),
            transaction_type=request.POST.get("transaction_type"),
            cost_price=request.POST.get("cost_price", 0),
            amount=request.POST.get("amount"),
        )
    return redirect("multichoice_dashboard")

@role_required("DIRECTOR")
def director_dashboard(request):

    from django.db.models import Sum, F, DecimalField, ExpressionWrapper
    from django.utils import timezone

    today = timezone.now().date()
    device_filter = request.GET.get("device")

    # ---------------- TELECOM DATA ----------------
    activities = ServiceActivity.objects.filter(
        date__year=today.year,
        date__month=today.month,
        approved=True
    ).select_related('staff', 'branch', 'device_tag')
    
    # Global Category Context for Sidebar
    categories = RetailCategory.objects.all()

    if device_filter:
        activities = activities.filter(device_tag_id=device_filter)

    branch_summary = activities.values("branch__name").annotate(
        total=Sum("quantity")
    ).order_by("-total")

    device_tags = DeviceTag.objects.all()

    # ---------------- REVENUE & PROFIT LOGIC ----------------
    all_sales_today = RetailSale.objects.filter(date=today)
    expenses_today = Expense.objects.filter(date=today)
    total_expenses = expenses_today.aggregate(total=Sum("amount"))["total"] or 0

    profit_expression = ExpressionWrapper(
        (F("selling_price") - F("product__cost_price")) * F("quantity"),
        output_field=DecimalField()
    )

    total_quantity = all_sales_today.aggregate(
        total=Sum("quantity")
    )["total"] or 0

    total_revenue = all_sales_today.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0

    gross_profit = all_sales_today.aggregate(
        total=Sum(profit_expression)
    )["total"] or 0
    
    net_profit = gross_profit - total_expenses

    # ---------------- MONTHLY ANALYTICS ----------------
    current_month = today.month
    current_year = today.year

    monthly_sales = RetailSale.objects.filter(
        date__month=current_month,
        date__year=current_year
    )
    monthly_expenses = Expense.objects.filter(
        date__month=current_month,
        date__year=current_year
    ).aggregate(total=Sum("amount"))["total"] or 0

    monthly_revenue = monthly_sales.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0

    monthly_gross_profit = monthly_sales.aggregate(
        total=Sum(
            ExpressionWrapper(
                (F("selling_price") - F("product__cost_price")) * F("quantity"),
                output_field=DecimalField()
            )
        )
    )["total"] or 0
    
    monthly_net_profit = monthly_gross_profit - monthly_expenses

    # ---------------- MULTICHOICE ANALYTICS ----------------
    all_multichoice_today = MultiChoiceSale.objects.filter(date=today)
    multichoice_total = all_multichoice_today.aggregate(
        total=Sum("amount")
    )["total"] or 0

    multichoice_by_branch = all_multichoice_today.values("branch__name").annotate(
        total_revenue=Sum("amount")
    ).order_by("-total_revenue")

    # ---------------- SALES PER BRANCH ----------------
    branch_performance = all_sales_today.values(
        "branch__name"
    ).annotate(
        total_qty=Sum("quantity"),
        total_revenue=Sum(F("quantity") * F("selling_price"))
    ).order_by("-total_revenue")

    # ---------------- TOP STAFF ----------------
    staff_performance = all_sales_today.values(
        "staff__username",
        "branch__name"
    ).annotate(
        total_qty=Sum("quantity"),
        total_revenue=Sum(F("quantity") * F("selling_price"))
    ).order_by("-total_revenue")[:10]

    # ---------------- TOP PRODUCTS ----------------
    top_products = all_sales_today.values(
        "product__model_name"
    ).annotate(
        total_qty=Sum("quantity")
    ).order_by("-total_qty")[:10]

    # ---------------- LOW STOCK ALERT ----------------
    low_stock = BranchSafeStock.objects.filter(
        quantity__lt=1
    )

    from .models import CheckInOutLog
    check_logs = CheckInOutLog.objects.filter(branch=request.user.branch).order_by('-date', '-check_in_time')[:20]

    context = {
        "branch_summary": branch_summary,
        "device_tags": device_tags,
        "selected_device": device_filter,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "total_profit": net_profit,
        "gross_profit": gross_profit,
        "total_expenses": total_expenses,
        "monthly_revenue": monthly_revenue,
        "monthly_profit": monthly_net_profit,
        "monthly_gross_profit": monthly_gross_profit,
        "monthly_expenses": monthly_expenses,
        "multichoice_total": multichoice_total,
        "multichoice_by_branch": multichoice_by_branch,
        "branch_performance": branch_performance,
        "staff_performance": staff_performance,
        "top_products": top_products,
        "low_stock": low_stock,
        "categories": categories,
        "check_logs": check_logs,
    }

    return render(request, "director_dashboard.html", context)

@role_required("DIRECTOR")
def director_safe_stock(request):
    stocks = DirectorSafeStock.objects.all().order_by('-date_added')
    products = Product.objects.all()
    categories = RetailCategory.objects.all()
    
    total_quantity = sum([s.quantity for s in stocks])
    total_value = sum([s.total_value for s in stocks])
    
    context = {
        'stocks': stocks,
        'products': products,
        'categories': categories,
        'total_quantity': total_quantity,
        'total_value': total_value,
    }
    return render(request, 'director/director_safe.html', context)

@role_required("DIRECTOR")
def add_director_stock(request):
    if request.method == "POST":
        product_id = request.POST.get('product_id')
        quantity = request.POST.get('quantity')
        notes = request.POST.get('notes', '')
        
        try:
            product = Product.objects.get(id=product_id)
            DirectorSafeStock.objects.create(
                product=product,
                quantity=int(quantity),
                notes=notes
            )
            messages.success(request, f"Added {quantity} {product.model_name} to director safe")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
    
    return redirect('director_safe_stock')

@role_required("DIRECTOR")
def delete_director_stock(request, stock_id):
    stock = DirectorSafeStock.objects.get(id=stock_id)
    product_name = stock.product.model_name if stock.product else "Stock"
    quantity = stock.quantity
    stock.delete()
    messages.success(request, f"Deleted {quantity} {product_name} from director safe")
    return redirect('director_safe_stock')

@role_required("DIRECTOR")
def create_director_product(request):
    if request.method == "POST":
        category_id = request.POST.get('category_id')
        new_cat_name = request.POST.get('new_category_name')
        subcat_name = request.POST.get('subcategory_name')
        subsubcat_name = request.POST.get('subsubcategory_name')
        
        # Get or create category
        if category_id == 'new':
            category, _ = RetailCategory.objects.get_or_create(name=new_cat_name)
        else:
            category = RetailCategory.objects.get(id=category_id)
        
        # Get or create subcategory
        subcategory, _ = RetailSubCategory.objects.get_or_create(category=category, name=subcat_name)
        
        # Get or create subsubcategory
        subsubcategory = None
        if subsubcat_name:
            subsubcategory, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=subsubcat_name)
        
        # Create product
        product = Product.objects.create(
            subcategory=subcategory,
            subsubcategory=subsubcategory,
            product_name=request.POST.get('product_name'),
            model_name=request.POST.get('model_name'),
            description=request.POST.get('description'),
            imei_serial=request.POST.get('imei_serial'),
            cost_price=request.POST.get('cost_price'),
            selling_price=request.POST.get('selling_price')
        )
        
        # Add to director safe
        quantity = int(request.POST.get('quantity'))
        DirectorSafeStock.objects.create(
            product=product,
            quantity=quantity,
            notes=f"Created by Director"
        )
        
        messages.success(request, f"Product created and added {quantity} units to safe")
    
    return redirect('director_safe_stock')

@login_required
def product_catalog(request):
    if request.user.role != "RETAIL":
        return HttpResponseForbidden("Access denied")
    
    products = Product.objects.all()
    categories = RetailCategory.objects.all()
    
    context = {
        'products': products,
        'categories': categories,
    }
    return render(request, 'retail_catalog.html', context)

@login_required
def add_stock_to_safe(request):
    if request.method == "POST" and request.user.role == "MANAGER":
        try:
            branch = request.user.branch
            
            # Check if creating new product
            if request.POST.get("is_new_product") == "true":
                cat_id = request.POST.get("category")
                subcat_name = request.POST.get("new_subcategory")
                subsubcat_name = request.POST.get("new_subsubcategory")
                
                category = RetailCategory.objects.get(id=cat_id)
                subcategory, _ = RetailSubCategory.objects.get_or_create(category=category, name=subcat_name)
                
                subsubcategory = None
                if subsubcat_name:
                    subsubcategory, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=subsubcat_name)
                
                product = Product.objects.create(
                    subcategory=subcategory,
                    subsubcategory=subsubcategory,
                    product_name=request.POST.get("product_name", ""),
                    model_name=request.POST.get("model_name"),
                    description=request.POST.get("description", ""),
                    imei_serial=request.POST.get("imei_serial", ""),
                    cost_price=float(request.POST.get("cost_price", 0)) or 0,
                    selling_price=float(request.POST.get("selling_price", 0)) or 0
                )
            else:
                product_id = request.POST.get("product")
                product = Product.objects.get(id=product_id)

            quantity = int(request.POST.get("quantity"))
            safe_stock, created = BranchSafeStock.objects.get_or_create(branch=branch, product=product)
            safe_stock.quantity += quantity
            safe_stock.save()

            StockMovement.objects.create(
                branch=branch, product=product, quantity=quantity,
                movement_type="IN", performed_by=request.user
            )
            messages.success(request, f"Added {quantity} of {product.model_name} to safe.")
        except Exception as e:
            messages.error(request, f"Error adding stock: {str(e)}")

    return redirect("manager_dashboard")

@login_required
def staff_create_product(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        try:
            cat_id = request.POST.get("category")
            subcat_name = request.POST.get("new_subcategory")
            subsubcat_name = request.POST.get("new_subsubcategory")
            
            category = RetailCategory.objects.get(id=cat_id)
            subcategory, _ = RetailSubCategory.objects.get_or_create(category=category, name=subcat_name)
            
            subsubcategory = None
            if subsubcat_name:
                subsubcategory, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=subsubcat_name)
            
            product = Product.objects.create(
                subcategory=subcategory,
                subsubcategory=subsubcategory,
                product_name=request.POST.get("product_name", ""),
                model_name=request.POST.get("model_name"),
                description=request.POST.get("description", ""),
                imei_serial=request.POST.get("imei", ""),
                cost_price=0,
                selling_price=float(request.POST.get("selling_price", 0)) or 0
            )
            
            quantity = int(request.POST.get("quantity", 1))
            staff_stock, _ = StaffStock.objects.get_or_create(staff=request.user, product=product)
            staff_stock.quantity += quantity
            staff_stock.save()
            
            messages.success(request, f"Product {product.model_name} created and added to your stock.")
        except Exception as e:
            messages.error(request, f"Error creating product: {str(e)}")
    return redirect("retail_dashboard")

@login_required
def add_category(request):
    if request.method == "POST" and request.user.role in ["MANAGER", "SUPERADMIN"]:
        name = request.POST.get("name")
        if name:
            RetailCategory.objects.get_or_create(name=name)
            messages.success(request, f"Category '{name}' added.")
    return redirect(request.META.get('HTTP_REFERER', 'manager_dashboard'))

@login_required
def release_stock(request):
    if request.method == "POST" and request.user.role == "MANAGER":
        branch = request.user.branch
        staff_id = request.POST.get("staff")
        product_id = request.POST.get("product")
        quantity = int(request.POST.get("quantity"))

        product = Product.objects.get(id=product_id)
        staff = User.objects.get(id=staff_id, branch=branch)

        safe_stock = BranchSafeStock.objects.get(
            branch=branch,
            product=product
        )

        # Prevent Over Release
        if quantity > safe_stock.quantity:
            messages.error(request, "Insufficient safe stock.")
            return redirect("manager_dashboard")

        # Reduce Safe Stock
        safe_stock.quantity -= quantity
        safe_stock.save()

        # Increase Staff Stock
        staff_stock, created = StaffStock.objects.get_or_create(
            staff=staff,
            product=product
        )

        staff_stock.quantity += quantity
        staff_stock.save()

        # Log Movement
        StockMovement.objects.create(
            branch=branch,
            product=product,
            quantity=quantity,
            movement_type="OUT",
            performed_by=request.user
        )
        messages.success(request, f"Released {quantity} of {product.model_name} to {staff.username}.")

    return redirect("manager_dashboard")

@login_required
def check_in(request):
    if request.method == "POST":
        user = request.user
        branch = user.branch

        if not branch or not branch.latitude or not branch.longitude:
            return JsonResponse({"error": "Branch location not configured"})

        latitude = float(request.POST.get("latitude"))
        longitude = float(request.POST.get("longitude"))
        selfie = request.FILES.get("selfie")

        today = timezone.now().date()

        if Attendance.objects.filter(user=user, date=today, session="morning").exists():
            return JsonResponse({"error": "Already checked in today"})

        distance = calculate_distance(latitude, longitude, branch.latitude, branch.longitude)

        if distance > branch.allowed_radius:
            return JsonResponse({
                "error": f"You are {distance:.0f}m away. Branch radius is {branch.allowed_radius}m. Please move closer or contact your director to adjust the radius.",
                "distance": round(distance, 2),
                "allowed_radius": branch.allowed_radius
            })

        status = attendance_status()
        attendance = Attendance.objects.create(
            user=user, branch=branch, session="morning", check_in_time=timezone.now(),
            latitude=latitude, longitude=longitude, distance_from_branch=distance, selfie=selfie
        )

        if status == "late":
            attendance.is_late = True
            attendance.deduction_amount = Decimal("250.00")
        elif status == "absent":
            attendance.is_absent = True

        attendance.save()
        return JsonResponse({"success": "Check in successful"})

    return render(request, "staff/attendance.html")

@login_required
def attendance_history(request):
    records = Attendance.objects.filter(user=request.user).order_by("-date")
    return render(request, "staff/attendance_history.html", {"records": records})

@role_required("DIRECTOR")
def director_attendance_dashboard(request):
    today = timezone.now().date()
    records = Attendance.objects.filter(date=today)
    context = {
        "records": records,
        "total_late": records.filter(is_late=True).count(),
        "total_absent": records.filter(is_absent=True).count(),
        "total_deductions": records.aggregate(Sum("deduction_amount"))["deduction_amount__sum"] or 0,
    }
    return render(request, "director/attendance.html", context)

@role_required("DIRECTOR")
def manage_branch_locations(request):
    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        latitude = request.POST.get("latitude")
        longitude = request.POST.get("longitude")
        allowed_radius = request.POST.get("allowed_radius", 100)
        
        try:
            branch = Branch.objects.get(id=branch_id)
            branch.latitude = float(latitude)
            branch.longitude = float(longitude)
            branch.allowed_radius = int(allowed_radius)
            branch.location_locked = True
            branch.save()
            messages.success(request, f"Location saved for {branch.name}")
        except Exception as e:
            messages.error(request, f"Error saving location: {str(e)}")
        
        return redirect("manage_branch_locations")
    
    branches = Branch.objects.all()
    return render(request, "director/manage_locations.html", {"branches": branches})

@login_required
def record_physical_product(request):
    if request.method == "POST" and request.user.role == "TELECOM":
        product_type = request.POST.get("product_type")
        quantity = int(request.POST.get("quantity"))
        price = float(request.POST.get("price"))
        
        ServiceActivity.objects.create(
            branch=request.user.branch,
            staff=request.user,
            service_type=product_type,
            quantity=quantity,
            date=timezone.now().date()
        )
        messages.success(request, f"Recorded {quantity} {product_type} at ₦{price} each")
    
    return redirect("staff_dashboard")

@role_required("DIRECTOR")
def export_monthly_attendance_pdf(request):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from io import BytesIO
    
    records = Attendance.objects.all().order_by("-date")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph("Monthly Attendance Report", styles['Heading1']))
    elements.append(Spacer(1, 0.3 * inch))
    
    data = [["Staff", "Date", "Late", "Absent", "Deduction"]]
    for r in records:
        data.append([
            r.user.username,
            str(r.date),
            "Yes" if r.is_late else "No",
            "Yes" if r.is_absent else "No",
            f"₦{r.deduction_amount}"
        ])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return HttpResponse(buffer, content_type="application/pdf", headers={'Content-Disposition': 'attachment; filename="Monthly_Attendance_Report.pdf"'})

# CSV Upload - Inventory Import
@role_required("DIRECTOR")
def upload_stock_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        import csv
        try:
            decoded = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded)
            count = 0
            for row in reader:
                BranchSafeStock.objects.update_or_create(
                    branch=request.user.branch,
                    product_id=row.get('product_id'),
                    defaults={'quantity': int(row.get('quantity', 0))}
                )
                count += 1
            messages.success(request, f"Imported {count} stock items successfully!")
        except Exception as e:
            messages.error(request, f"CSV error: {str(e)}")
    return redirect('director_dashboard')

# CRM Dashboard - Customer Analytics
@role_required("DIRECTOR")
def customer_crm(request):
    from .models import Customer
    customers = Customer.objects.filter(branch=request.user.branch).order_by('-last_purchase')
    search = request.GET.get('search', '')
    if search:
        from django.db.models import Q
        customers = customers.filter(Q(name__icontains=search) | Q(phone_number__icontains=search))
    
    context = {
        'customers': customers,
        'total_customers': customers.count(),
        'search': search,
    }
    return render(request, 'customer_crm.html', context)

# Stock Alerts
@login_required
def stock_alerts(request):
    from .models import StockAlert
    alerts = StockAlert.objects.filter(branch=request.user.branch, is_active=True)
    context = {'alerts': alerts}
    return render(request, 'stock_alerts.html', context)

# Staff Checkout for Outings
@role_required("MANAGER")
def staff_checkout(request, staff_id):
    from .models import CheckInOutLog
    if request.method == 'POST':
        purpose = request.POST.get('purpose', 'Office outing')
        CheckInOutLog.objects.create(
            staff_id=staff_id,
            branch=request.user.branch,
            check_in_time=timezone.now(),
            purpose=purpose,
            is_checkout=True
        )
        messages.success(request, "Staff checked out")
    return redirect('manager_dashboard')

# Staff Checkin from Outings
@role_required("MANAGER")
def staff_checkin(request, staff_id):
    from .models import CheckInOutLog
    last_checkout = CheckInOutLog.objects.filter(
        staff_id=staff_id,
        is_checkout=True,
        check_out_time__isnull=True
    ).last()
    
    if last_checkout:
        last_checkout.check_out_time = timezone.now()
        last_checkout.save()
        messages.success(request, "Staff checked in")
    
    return redirect('manager_dashboard')

# Device Tag Commission Tracking
@role_required("MANAGER")
def add_device_commission(request):
    from .models import DeviceTagCommission
    device_tags = DeviceTag.objects.filter(branch=request.user.branch)
    
    if request.method == 'POST':
        device_tag_id = request.POST.get('device_tag_id')
        month_year = request.POST.get('month_year')
        commission = request.POST.get('commission_amount')
        
        DeviceTagCommission.objects.update_or_create(
            branch=request.user.branch,
            device_tag_id=device_tag_id,
            month_year=month_year,
            defaults={'commission_amount': commission, 'created_by': request.user}
        )
        messages.success(request, "Commission recorded successfully")
        return redirect('manager_dashboard')
    
    context = {'device_tags': device_tags}
    return render(request, 'device_commission_form.html', context)

# MultiChoice Commission Tracking - Daily Balance & Detection
@login_required
def record_daily_balance(request):
    from .models import CommissionPayment
    from datetime import timedelta
    
    if request.method == 'POST' and request.user.role == 'MULTICHOICE':
        balance = Decimal(request.POST.get('balance', 0))
        notes = request.POST.get('notes', '')
        
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        
        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start
        )
        
        balance_record = MultiChoiceBalance.objects.create(
            weekly_report=weekly_report,
            balance_amount=balance,
            notes=notes
        )
        
        # Detect commission (check if balance increased from yesterday)
        prev_balance = MultiChoiceBalance.objects.filter(
            weekly_report__staff=request.user,
            date__lt=today
        ).order_by('-date', '-time').first()
        
        if prev_balance and balance > prev_balance.balance_amount:
            commission_amt = balance - prev_balance.balance_amount
            balance_record.is_commission_payment = True
            balance_record.save()
            
            CommissionPayment.objects.create(
                staff=request.user,
                branch=request.user.branch,
                balance_record=balance_record,
                previous_balance=prev_balance.balance_amount,
                current_balance=balance,
                commission_detected=commission_amt,
                date_paid=today
            )
            messages.success(request, f"✅ Commission detected & recorded: ₦{commission_amt:,.2f}")
        else:
            messages.success(request, f"✓ Balance recorded: ₦{balance:,.2f}")
    
    return redirect('multichoice_dashboard')

# Director - View all commissions paid to staff
@role_required("DIRECTOR")
def commission_tracking(request):
    from .models import CommissionPayment
    from datetime import timedelta
    
    commissions = CommissionPayment.objects.filter(
        branch=request.user.branch
    ).select_related('staff').order_by('-date_detected')
    
    total_commissions = commissions.aggregate(total=Sum('commission_detected'))['total'] or 0
    
    staff_filter = request.GET.get('staff')
    if staff_filter:
        commissions = commissions.filter(staff_id=staff_filter)
    
    staff_list = User.objects.filter(branch=request.user.branch, role='MULTICHOICE')
    
    context = {
        'commissions': commissions,
        'total_commissions': total_commissions,
        'staff_list': staff_list,
        'selected_staff': staff_filter,
    }
    return render(request, 'commission_tracking.html', context)

# MultiChoice Staff - View their commission history
@login_required
def my_commissions(request):
    from .models import CommissionPayment
    
    if request.user.role != 'MULTICHOICE':
        return HttpResponseForbidden("Not allowed")
    
    commissions = CommissionPayment.objects.filter(
        staff=request.user
    ).order_by('-date_detected')
    
    total_earned = commissions.aggregate(total=Sum('commission_detected'))['total'] or 0
    
    context = {
        'commissions': commissions,
        'total_earned': total_earned,
    }
    return render(request, 'my_commissions.html', context)

@login_required
def edit_staff_stock_price(request, stock_id):
    """Allow retail staff to edit selling price of their stock"""
    if request.user.role != "RETAIL":
        messages.error(request, "Access denied.")
        return redirect("retail_dashboard")
    
    try:
        stock = StaffStock.objects.get(id=stock_id, staff=request.user)
        new_price = request.GET.get('price')
        
        if new_price:
            stock.product.selling_price = float(new_price)
            stock.product.save()
            messages.success(request, f"Price updated to ₦{new_price} for {stock.product.model_name}")
    except StaffStock.DoesNotExist:
        messages.error(request, "Stock not found.")
    
    return redirect("retail_dashboard")

@role_required("DIRECTOR")
def edit_director_stock(request, stock_id):
    """Allow director to edit quantity of safe stock"""
    try:
        stock = DirectorSafeStock.objects.get(id=stock_id)
        new_quantity = request.GET.get('quantity')
        
        if new_quantity:
            new_qty = int(new_quantity)
            old_qty = stock.quantity
            stock.quantity = new_qty
            stock.save()
            messages.success(request, f"Updated {stock.product.model_name} quantity from {old_qty} to {new_qty}")
    except DirectorSafeStock.DoesNotExist:
        messages.error(request, "Stock not found.")
    
    return redirect("director_safe_stock")

@login_required
def edit_product_price(request, product_id):
    """Allow retail staff to edit product selling price from catalog"""
    try:
        product = Product.objects.get(id=product_id)
        new_price = request.GET.get('price')
        
        if new_price:
            product.selling_price = float(new_price)
            product.save()
            messages.success(request, f"Price updated to ₦{new_price} for {product.model_name}")
    except Product.DoesNotExist:
        messages.error(request, "Product not found.")
    
    return redirect("product_catalog")
