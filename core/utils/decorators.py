from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from functools import wraps

def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            from core.roles import effective_roles  # ROLES_V1
            if not (set(roles) & effective_roles(request.user)):
                return HttpResponseForbidden("You do not have permission to access this page.")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
