from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
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

@role_required("MANAGER")
def stock_movement_log(request):
    branch        = request.user.branch
    movement_type = request.GET.get("type", "")
    date_from     = request.GET.get("date_from", "")
    date_to       = request.GET.get("date_to", "")
    export        = request.GET.get("export", "")

    movements = StockMovement.objects.filter(
        branch=branch
    ).select_related("product", "performed_by").order_by("-date", "-time")

    if movement_type:
        movements = movements.filter(movement_type=movement_type)
    if date_from:
        movements = movements.filter(date__gte=date_from)
    if date_to:
        movements = movements.filter(date__lte=date_to)

    total_in  = movements.filter(movement_type="IN").aggregate(t=Sum("quantity"))["t"] or 0
    total_out = movements.filter(movement_type="OUT").aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        return _stock_log_pdf(movements, branch, date_from, date_to, movement_type)

    paginator = Paginator(movements, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "manager/stock_log.html", {
        "movements": page,
        "total_in": total_in,
        "total_out": total_out,
        "selected_type": movement_type,
        "date_from": date_from,
        "date_to": date_to,
    })


