from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from datetime import date
from django.db.models import Sum
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity

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
            if role == 'staff':
                return redirect('staff_dashboard')
            elif role == 'manager':
                return redirect('manager_dashboard')
            elif role in ['director', 'super_admin']:
                return redirect('director_dashboard')
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
    if not request.user.is_superuser and request.user.role != 'staff':
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

        ServiceActivity.objects.create(
            staff=request.user,
            branch=request.user.branch,
            service_type=service_type,
            quantity=quantity,
            device_tag_id=device_tag_id
        )
        return redirect("staff_dashboard")

    target_data = []
    for target in targets:
        achieved = activities.filter(
            service_type=target.service_type
        ).aggregate(total=Sum("quantity"))["total"] or 0

        remaining = target.target_number - achieved
        percentage = 0
        if target.target_number > 0:
            percentage = (achieved / target.target_number) * 100

        target_data.append({
            "service_type": target.service_type,
            "target_number": target.target_number,
            "achieved": achieved,
            "remaining": max(remaining, 0),
            "percentage": round(percentage, 2),
        })

    device_tags = DeviceTag.objects.filter(branch=request.user.branch)
    context = {
        "target_data": target_data,
        "device_tags": device_tags,
        "activities": activities
    }
    return render(request, "staff_dashboard.html", context)

# -----------------------
# Manager Dashboard
# -----------------------
@login_required
def manager_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'manager':
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

    context = {
        'target_data': target_data,
        'activities': activities
    }
    return render(request, 'manager_dashboard.html', context)

# -----------------------
# Director Dashboard
# -----------------------
@login_required
def director_dashboard(request):
    if not request.user.is_superuser and request.user.role not in ['director', 'super_admin']:
        return HttpResponseForbidden("Not allowed")

    today = date.today()
    targets = ServiceTarget.objects.filter(
        date__year=today.year,
        date__month=today.month
    )

    activities = ServiceActivity.objects.filter(
        date__year=today.year,
        date__month=today.month
    )

    total_target = targets.aggregate(total=Sum("target_number"))["total"] or 0
    total_achieved = activities.aggregate(total=Sum("quantity"))["total"] or 0

    overall_percentage = 0
    if total_target > 0:
        overall_percentage = (total_achieved / total_target) * 100

    top_staff = activities.values("staff__username") \
        .annotate(total=Sum("quantity")) \
        .order_by("-total")[:5]

    context = {
        "total_target": total_target,
        "total_achieved": total_achieved,
        "overall_percentage": round(overall_percentage, 2),
        "top_staff": top_staff,
        "targets": targets,
        "branches": Branch.objects.all(),
        "today": today.isoformat()
    }
    return render(request, "director_dashboard.html", context)
