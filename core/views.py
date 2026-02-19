from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from datetime import date
from .models import User, Branch, DeviceTag, ServiceTarget, ServiceActivity

# -----------------------
# Custom Login
# -----------------------
def custom_login(request):
    # Log out user if they are already logged in to prevent session conflicts
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

            # ✅ Allow Django superuser automatically
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
@login_required
def staff_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'staff':
        return HttpResponseForbidden("Not allowed")

    today = date.today()

    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date=today
    )

    device_tags = DeviceTag.objects.filter(branch=request.user.branch)

    if request.method == 'POST':
        service_type = request.POST.get('service_type')
        quantity = int(request.POST.get('quantity') or 0)
        device_tag_id = request.POST.get('device_tag')

        device_tag = None
        if service_type == 'sim_registration' and device_tag_id:
            try:
                device_tag = DeviceTag.objects.get(id=device_tag_id, branch=request.user.branch)
            except DeviceTag.DoesNotExist:
                pass

        ServiceActivity.objects.create(
            branch=request.user.branch,
            staff=request.user,
            service_type=service_type,
            quantity=quantity,
            device_tag=device_tag
        )

        return redirect('staff_dashboard')

    return render(request, 'staff_dashboard.html', {
        'targets': targets,
        'device_tags': device_tags
    })


# -----------------------
# Manager Dashboard
# -----------------------
from django.db.models import Sum

@login_required
def manager_dashboard(request):
    if not request.user.is_superuser and request.user.role != 'manager':
        return HttpResponseForbidden("Not allowed")

    today = date.today()

    # Monthly targets
    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date__year=today.year,
        date__month=today.month
    )

    # Monthly activities
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
            'remaining': remaining if remaining > 0 else 0,
            'percentage': round(percentage, 2)
        })

    context = {
        'target_data': target_data,
        'activities': activities
    }

    return render(request, 'manager_dashboard.html', context)


# -----------------------
# Director / Super Admin Dashboard
# -----------------------
@login_required
def director_dashboard(request):
    # Allow Django superuser automatically
    if not request.user.is_superuser:
        if request.user.role not in ['director', 'super_admin']:
            return HttpResponseForbidden("Not allowed")

    today = date.today()
    branches = Branch.objects.all()

    if request.method == 'POST':
        branch_id = request.POST.get('branch')
        service_type = request.POST.get('service_type')
        target_number = request.POST.get('target_number')
        target_date = request.POST.get('date') or today

        ServiceTarget.objects.update_or_create(
            branch_id=branch_id,
            service_type=service_type,
            date=target_date,
            defaults={
                'target_number': target_number,
                'created_by': request.user
            }
        )

        return redirect('director_dashboard')

    targets = ServiceTarget.objects.filter(date=today)

    return render(request, 'director_dashboard.html', {
        'branches': branches,
        'targets': targets,
        'today': today.isoformat()
    })
