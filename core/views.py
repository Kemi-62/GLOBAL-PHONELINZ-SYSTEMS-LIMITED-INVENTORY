from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from datetime import date
from django.db.models import Sum, F
from django.utils import timezone
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity, BranchSafeStock, StockMovement, MultiChoiceActivity, Product, StaffStock, RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory

# -----------------------
# Custom Login
# -----------------------
def custom_login(request):
    if request.user.is_authenticated and request.method == 'GET':
        from django.contrib.auth import logout
        logout(request)
        return redirect('login')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        try:
            user_record = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "Invalid credentials")
            return redirect('login')

        if hasattr(user_record, 'is_locked') and user_record.is_locked:
            messages.error(request, "Account locked. Contact Admin.")
            return redirect('login')

        user_auth = authenticate(request, username=username, password=password)

        if user_auth is not None:
            if hasattr(user_record, 'failed_login_count'):
                user_record.failed_login_count = 0
            if hasattr(user_record, 'failed_attempts'):
                user_record.failed_attempts = 0
            user_record.save()
            login(request, user_auth)

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
            elif role == "SUPERADMIN":
                return redirect("/admin/")
            else:
                messages.error(request, "No role assigned. Contact Admin.")
                return redirect('login')
        else:
            if hasattr(user_record, 'failed_login_count'):
                user_record.failed_login_count += 1
            if hasattr(user_record, 'failed_attempts'):
                user_record.failed_attempts += 1
            user_record.save()
            messages.error(request, "Invalid credentials")
            return redirect('login')

    return render(request, 'login.html')

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

    context = {
        "device_progress": device_progress,
        "device_tags": DeviceTag.objects.filter(branch=request.user.branch),
        "activities": activities,
        "pending_activities": pending_activities,
        "monthly_total": monthly_total,
    }
    return render(request, "staff_dashboard.html", context)

# -----------------------
# Manager Dashboard
# -----------------------
@login_required
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
    multichoice_today = MultiChoiceActivity.objects.filter(
        staff__branch=branch,
        date=today_date
    ).aggregate(total=Sum("quantity"))["total"] or 0

    # ---------------- RETAIL SALES TODAY ----------------
    retail_sales_today = RetailSale.objects.filter(
        branch=branch,
        date=today_date
    )

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

    context = {
        'target_data': target_data,
        'activities': activities,
        'pending_approvals': pending_approvals,
        "safe_stocks": safe_stocks,
        "categories": categories,
        "retail_staff": retail_staff,
        "today_movements": today_movements,
        "total_stock_out": total_stock_out,
        "multichoice_today": multichoice_today,
        "total_retail_quantity": total_retail_quantity,
        "total_retail_revenue": total_retail_revenue,
        "sales_per_staff": sales_per_staff,
        "top_products": top_products,
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

@login_required
def retail_dashboard(request):
    if request.user.role != "RETAIL":
        return redirect("login")

    staff = request.user
    staff_stock = StaffStock.objects.filter(staff=staff)

    return render(request, "retail_dashboard.html", {
        "staff_stock": staff_stock
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
            selling_price=selling_price
        )
        messages.success(request, "Sale recorded successfully.")

    return redirect("retail_dashboard")

@login_required
def multichoice_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'MULTICHOICE':
        return HttpResponseForbidden("Not allowed")
    return render(request, "multichoice_dashboard.html")

@login_required
def director_dashboard(request):
    if not request.user.is_superuser and request.user.role not in ['DIRECTOR', 'SUPERADMIN']:
        return HttpResponseForbidden("Not allowed")

    today = timezone.now().date()
    device_filter = request.GET.get("device")

    # ---------------- TELECOM DATA ----------------
    activities = ServiceActivity.objects.filter(
        date__year=today.year,
        date__month=today.month,
        approved=True
    )

    if device_filter:
        activities = activities.filter(device_tag_id=device_filter)

    branch_summary = activities.values("branch__name").annotate(
        total=Sum("quantity")
    ).order_by("-total")

    device_tags = DeviceTag.objects.all()

    # ---------------- ALL RETAIL SALES TODAY ----------------
    all_sales_today = RetailSale.objects.filter(date=today)

    total_quantity = all_sales_today.aggregate(
        total=Sum("quantity")
    )["total"] or 0

    total_revenue = all_sales_today.aggregate(
        total=Sum(F("quantity") * F("selling_price"))
    )["total"] or 0

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
        quantity__lt=5
    )

    context = {
        "branch_summary": branch_summary,
        "device_tags": device_tags,
        "selected_device": device_filter,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "branch_performance": branch_performance,
        "staff_performance": staff_performance,
        "top_products": top_products,
        "low_stock": low_stock,
    }

    return render(request, "director_dashboard.html", context)

@login_required
def add_stock_to_safe(request):
    if request.method == "POST" and request.user.role == "MANAGER":
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
                product_name=request.POST.get("product_name"),
                model_name=request.POST.get("model_name"),
                description=request.POST.get("description"),
                imei_last_5=request.POST.get("imei"),
                cost_price=request.POST.get("cost_price", 0),
                selling_price=request.POST.get("selling_price")
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

    return redirect("manager_dashboard")

@login_required
def staff_create_product(request):
    if request.method == "POST" and request.user.role == "RETAIL":
        # Implementation for staff creating product directly (non-safe stock)
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
            product_name=request.POST.get("product_name"),
            model_name=request.POST.get("model_name"),
            description=request.POST.get("description"),
            imei_last_5=request.POST.get("imei"),
            cost_price=request.POST.get("cost_price", 0),
            selling_price=request.POST.get("selling_price")
        )
        
        quantity = int(request.POST.get("quantity"))
        staff_stock, _ = StaffStock.objects.get_or_create(staff=request.user, product=product)
        staff_stock.quantity += quantity
        staff_stock.save()
        
        messages.success(request, f"Product {product.model_name} created and added to your stock.")
    return redirect("retail_dashboard")

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

    return redirect("manager_dashboard")
