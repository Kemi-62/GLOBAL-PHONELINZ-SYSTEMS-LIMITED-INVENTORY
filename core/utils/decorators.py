from django.shortcuts import redirect
from functools import wraps
from django.core.mail import send_mail
from django.utils import timezone
from datetime import time
from django.contrib.auth import get_user_model

User = get_user_model()

def role_required(role):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if request.user.role != role:
                return redirect("login")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

def send_absent_alert():
    from django.utils import timezone
    from datetime import time
    from django.apps import apps
    
    now = timezone.localtime().time()
    if now < time(8, 30):
        return
    
    today = timezone.now().date()
    staff = User.objects.exclude(role__in=["DIRECTOR", "SUPERADMIN"]).filter(role__isnull=False)
    Attendance = apps.get_model('core', 'Attendance')
    
    absent_staff = []
    for user in staff:
        checked = Attendance.objects.filter(user=user, date=today).exists()
        if not checked:
            absent_staff.append(user.username)
    
    if absent_staff:
        message = "Staff not checked in today:\n\n"
        for s in absent_staff:
            message += f"- {s}\n"
        
        try:
            send_mail(
                "Attendance Alert",
                message,
                "system@company.com",
                ["director@company.com"],
                fail_silently=True
            )
        except:
            pass
