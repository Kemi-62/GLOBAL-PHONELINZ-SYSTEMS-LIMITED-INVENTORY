from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.http import HttpResponseForbidden
from datetime import date
from .models import *

# -----------------------
# Custom Login
# -----------------------
def custom_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "Invalid credentials")
            return redirect('login')

        if user.failed_login_count >= 3:
            messages.error(request, "Account locked. Contact Admin.")
            return redirect('login')

        user_auth = authenticate(request, username=username, password=password)

        if user_auth:
            user.failed_login_count = 0
            user.save()
            login(request, user_auth)

            if user.role == 'staff':
                return redirect('staff_dashboard')
            elif user.role == 'manager':
                return redirect('manager_dashboard')
            else:
                return redirect('director_dashboard')

        else:
            user.failed_login_count += 1
            user.save()
            messages.error(request, "Invalid credentials")
            return redirect('login')

    return render(request, 'login.html')


# -----------------------
# Staff Dashboard
# -----------------------
def staff_dashboard(request):
    today = date.today()

    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date=today
    )

    device_tags = DeviceTag.objects.filter(branch=request.user.branch)

    if request.method == 'POST':
        service_type = request.POST.get('service_type')
        quantity = int(request.POST.get('quantity'))
        device_tag_id = request.POST.get('device_tag')

        device_tag = None
        if service_type == 'sim_registration':
            device_tag = DeviceTag.objects.get(id=device_tag_id)

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
def manager_dashboard(request):
    today = date.today()

    targets = ServiceTarget.objects.filter(
        branch=request.user.branch,
        date=today
    )

    activities = ServiceActivity.objects.filter(
        branch=request.user.branch,
        date=today
    )

    return render(request, 'manager_dashboard.html', {
        'targets': targets,
        'activities': activities
    })


# -----------------------
# Director / Super Admin Dashboard
# -----------------------
def director_dashboard(request):

    if request.user.role not in ['director', 'super_admin']:
        return HttpResponseForbidden("Not allowed")

    today = date.today()
    branches = Branch.objects.all()

    if request.method == 'POST':
        branch_id = request.POST.get('branch')
        service_type = request.POST.get('service_type')
        target_number = request.POST.get('target_number')
        target_date = request.POST.get('date')

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
        'targets': targets
    })
