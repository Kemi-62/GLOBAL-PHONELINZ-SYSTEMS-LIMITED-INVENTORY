from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView as DjPRCV
from django.db import transaction
from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings as django_settings
from decimal import Decimal
from datetime import date, time, timedelta
import math
import csv
import io
try:
    import PIL.Image as _PILImage
except ImportError:
    _PILImage = None

from core.models import (
    User, Branch, DeviceTag, ServiceTarget, ServiceActivity,
    BranchSafeStock, StockMovement, Product, StaffStock,
    RetailSale, RetailCategory, RetailSubCategory, RetailSubSubCategory,
    MultiChoiceSale, MultiChoiceWeeklyReport, MultiChoiceBalance,
    Expense, StockRequest, Attendance, DirectorSafeStock,
    CheckInOutLog, SimInventory, SimInventoryLog,
    Customer, StockAlert, DeviceTagCommission, CommissionPayment,
    Invoice, WholesaleDeviceSale,
    MoniepointTransaction, LoyaltyPoint, LoyaltyTransaction
)
from core.models import log_action
from core.utils.decorators import role_required
from .helpers import _redirect_by_role

def custom_login(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, "login.html")

        user = authenticate(request, username=username, password=password)
        if user:
            if getattr(user, "is_locked", False):
                messages.error(request, "This account is locked. Contact your director.")
                return render(request, "login.html")
            login(request, user)
            user.failed_login_count = 0
            user.save(update_fields=["failed_login_count"])
            return _redirect_by_role(user)
        else:
            # Mark failed login for middleware rate limiting
            request._failed_login = True
            # Also track in model for account-level locking
            try:
                u = User.objects.get(username=username)
                if not u.is_superuser:
                    u.failed_login_count = (u.failed_login_count or 0) + 1
                    if u.failed_login_count >= 5:
                        u.is_locked = True
                        messages.error(request, "Too many failed attempts. Account locked.")
                    else:
                        messages.error(request, f"Invalid credentials. {5 - u.failed_login_count} attempt(s) remaining.")
                u.save(update_fields=["failed_login_count", "is_locked"])
            except User.DoesNotExist:
                messages.error(request, "Invalid credentials.")

    return render(request, "login.html")



def user_logout(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("login")



def csrf_failure(request, reason=""):
    messages.error(request, "Your session expired. Please log in again.")
    return redirect("login")



def admin_redirect(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return _redirect_by_role(request.user)


# ─────────────────────────────────────────
# STAFF / TELECOM DASHBOARD
# ─────────────────────────────────────────


class CustomPasswordResetConfirmView(DjPRCV):
    template_name = "registration/password_reset_confirm.html"

    def form_valid(self, form):
        user = form.save()
        # Force save using set_password properly
        new_password = form.cleaned_data.get("new_password1")
        user.set_password(new_password)
        user.save()
        messages.success(self.request, "Password updated successfully. Please log in with your new password.")
        return redirect("login")


# ─────────────────────────────────────────
# DIRECTOR SAFE STOCK — with all_branches, all_staff, date filter, log
# ─────────────────────────────────────────

