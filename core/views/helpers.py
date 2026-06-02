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

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))



def _get_dashboard_url(user):
    """Return the dashboard URL name for the given user's role."""
    from django.urls import reverse
    role_map = {
        "DIRECTOR":    "director_dashboard",
        "SUPERADMIN":  "director_dashboard",
        "MANAGER":     "manager_dashboard",
        "RETAIL":      "retail_dashboard",
        "MULTICHOICE": "multichoice_dashboard",
        "TELECOM":     "staff_dashboard",
    }
    if getattr(user, "is_superuser", False):
        return reverse("director_dashboard")
    name = role_map.get(getattr(user, "role", None), "login")
    return reverse(name)



def _get_director_phone():
    """Return the director's WhatsApp number from settings."""
    return getattr(django_settings, "DIRECTOR_WHATSAPP", "")



def send_whatsapp(phone, message):
    """Send a WhatsApp message via CallMeBot API. Returns True on success."""
    if not phone:
        return False
    import urllib.request
    import urllib.parse
    api_key = getattr(django_settings, "CALLMEBOT_API_KEY", "")
    if not api_key:
        return False
    try:
        encoded = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={api_key}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False



def attendance_status():
    now = timezone.localtime()
    t = now.time()
    wd = now.weekday()
    if wd < 5:   # Mon–Fri
        if time(7, 30) <= t <= time(8, 0):   return "ontime"
        if time(8, 1)  <= t <= time(8, 59):  return "late"
        if t >= time(9, 0):                   return "absent"
    if wd == 5:  # Saturday
        if time(9, 0) <= t <= time(9, 15):   return "ontime"
        if t > time(9, 15):                   return "late"
    return "early"


# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────

ROLE_REDIRECTS = {
    "DIRECTOR":   "director_dashboard",
    "SUPERADMIN": "director_dashboard",
    "MANAGER":    "manager_dashboard",
    "RETAIL":     "retail_dashboard",
    "MULTICHOICE":"multichoice_dashboard",
    "TELECOM":    "staff_dashboard",
}


def _redirect_by_role(user):
    if user.is_superuser:
        return redirect("director_dashboard")
    return redirect(ROLE_REDIRECTS.get(getattr(user, "role", None), "login"))



def _stock_log_pdf(movements, branch, date_from, date_to, movement_type):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#004F9F")

    label = f"{branch.name} Stock Log"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} → {date_to or 'Today'}"
    if movement_type:
        label += f"  |  {movement_type} only"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]

    data = [["Date", "Time", "Product", "Type", "Qty", "Done By"]]
    for m in movements:
        data.append([
            m.date.strftime("%d %b %Y"),
            m.time.strftime("%H:%M") if m.time else "—",
            m.product.model_name[:35],
            m.movement_type,
            str(m.quantity),
            m.performed_by.username if m.performed_by else "—",
        ])

    t = Table(data, colWidths=[1.1*inch, 0.7*inch, 2.2*inch, 0.9*inch, 0.6*inch, 1.2*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("ALIGN",         (3,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.15*inch))
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — Global Phonelinz Systems Ltd",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER)
    ))

    doc.build(elements)
    buffer.seek(0)
    fname = f"StockLog_{branch.name}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buffer, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# MULTICHOICE HISTORY — PDF download filtered
# ─────────────────────────────────────────


def _director_safe_pdf(stocks, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()
    label = f"Director Safe Stock"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]
    data = [["Product", "Category", "Cost Price", "Sell Price", "Qty", "Value", "Date Added"]]
    for s in stocks:
        data.append([
            s.product.model_name if s.product else "—",
            s.product.subcategory.name if s.product and s.product.subcategory else "—",
            f"N{s.product.cost_price:,.0f}" if s.product else "—",
            f"N{s.product.selling_price:,.0f}" if s.product else "—",
            str(s.quantity),
            f"N{s.total_value:,.0f}",
            s.date_added.strftime("%d %b %Y") if s.date_added else "—",
        ])
    t = Table(data, colWidths=[1.8*inch, 1.1*inch, 0.9*inch, 0.9*inch, 0.5*inch, 0.9*inch, 0.9*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — GPSL",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7, textColor=colors.grey, alignment=TA_CENTER, spaceBefore=10)
    ))
    doc.build(elements)
    buf.seek(0)
    fname = f"DirectorSafe_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})



def _retail_sales_pdf(sales, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Sales History"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    data = [["Date", "Time", "Product", "Qty", "Price", "Total", "Payment", "Status"]]
    total = Decimal(0)
    for s in sales:
        amt = Decimal(s.quantity) * s.selling_price
        if not s.is_voided:
            total += amt
        data.append([
            s.date.strftime("%d %b %Y"),
            s.time.strftime("%H:%M") if s.time else "—",
            s.product.model_name[:28],
            str(s.quantity),
            f"N{s.selling_price:,.0f}",
            f"N{amt:,.0f}",
            s.payment_method,
            "VOIDED" if s.is_voided else "Active",
        ])
    data.append(["", "", "", "", "", f"N{total:,.0f}", "TOTAL", ""])
    t = Table(data, colWidths=[0.85*inch, 0.6*inch, 1.8*inch, 0.45*inch, 0.75*inch, 0.75*inch, 0.75*inch, 0.65*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#F3F4F6")),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7.5),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"SalesHistory_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# ATTENDANCE HISTORY — with date range + download
# ─────────────────────────────────────────


def _attendance_pdf(qs, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Attendance History"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    data = [["Date", "Check In", "Check Out", "Status", "Distance", "Deduction"]]
    for r in qs:
        data.append([
            r.date.strftime("%d %b %Y"),
            r.check_in_time.strftime("%H:%M") if r.check_in_time else "—",
            r.check_out_time.strftime("%H:%M") if r.check_out_time else "Not out",
            "ABSENT" if r.is_absent else ("LATE" if r.is_late else "ON TIME"),
            f"{r.distance_from_branch:.0f}m" if r.distance_from_branch else "—",
            f"N{r.deduction_amount:,.2f}" if r.deduction_amount else "—",
        ])
    t = Table(data, colWidths=[1*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.9*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    fname = f"Attendance_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# DIRECTOR SALES REPORT — with date range + download
# ─────────────────────────────────────────


def _director_sales_pdf(branch_summary, total_qty, total_revenue, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"Sales Report  |  {date_from or 'All'} to {date_to or 'Today'}"
    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
    ]
    for bn, data in branch_summary.items():
        bh = Table([[Paragraph(f"  {bn}", ParagraphStyle("bh", parent=styles["Normal"], fontSize=10, textColor=colors.white, fontName="Helvetica-Bold"))]],
                   colWidths=[7.5*inch])
        bh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#374151")),
                                 ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        elements.append(bh)
        rows = [["Date", "Time", "Product", "Staff", "Qty", "Price", "Total"]]
        for s in data["sales"]:
            rows.append([
                s["date"].strftime("%d %b %Y") if s["date"] else "—",
                s["time"].strftime("%H:%M") if s["time"] else "—",
                str(s["product"])[:28],
                str(s["staff"]),
                str(s["quantity"]),
                f"N{s['price']:,.0f}",
                f"N{s['amount']:,.0f}",
            ])
        rows.append(["","","","BRANCH TOTAL", str(data["total_qty"]),"",f"N{data['total_revenue']:,.0f}"])
        t = Table(rows, colWidths=[0.85*inch,0.6*inch,1.8*inch,1*inch,0.5*inch,0.8*inch,0.85*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E5E7EB")),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#F0FDF4")),
            ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),7.5),
            ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white,colors.HexColor("#F9FAFB")]),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.12*inch))

    # Grand total
    gt = Table([[f"GRAND TOTAL — {total_qty} items", f"N{total_revenue:,.0f}"]], colWidths=[5*inch, 2.5*inch])
    gt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BLUE),("TEXTCOLOR",(0,0),(-1,-1),colors.white),
        ("FONTNAME",(0,0),(-1,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),10),
        ("ALIGN",(1,0),(1,0),"RIGHT"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
    ]))
    elements.append(gt)
    doc.build(elements)
    buf.seek(0)
    fname = f"SalesReport_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ","_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# MANAGER SALES HISTORY — date range + staff + download
# ─────────────────────────────────────────


def _earn_loyalty_points(customer, branch, amount, source):
    """Auto-earn loyalty points: 1 point per N100 spent."""
    if not amount or amount <= 0:
        return
    points = int(Decimal(str(amount)) / 100)
    if points < 1:
        return

    from decimal import Decimal
    lp, _ = LoyaltyPoint.objects.get_or_create(
        customer=customer,
        branch=branch,
        defaults={'points_balance': 0, 'total_earned': 0, 'total_redeemed': 0, 'tier': 'BRONZE'}
    )
    lp.points_balance += points
    lp.total_earned += points
    lp.save(update_fields=['points_balance', 'total_earned'])
    lp.update_tier()

    LoyaltyTransaction.objects.create(
        loyalty_point=lp,
        transaction_type='EARN',
        points=points,
        amount_spent=Decimal(str(amount)),
        description=f"Points earned from {source} purchase",
        sale_type=source,
    )



def _upsert_customer(phone, name, branch, amount=0, source="RETAIL"):
    """
    Create or update a customer record from any sale source.
    phone: customer phone number (required)
    name: customer name (optional, uses existing or 'Unknown')
    branch: branch object
    amount: sale amount to add to total_spent
    source: RETAIL, MULTICHOICE, TELECOM
    """
    if not phone or not phone.strip():
        return None
    phone = phone.strip()
    try:
        customer, created = Customer.objects.get_or_create(
            phone_number=phone,
            defaults={
                "name": (name or "").strip() or "Unknown",
                "branch": branch,
                "purchase_count": 0,
                "total_spent": Decimal("0"),
            }
        )
        # Update name if we now have one and didn't before
        if not created and name and name.strip() and customer.name in ("Unknown", "", None):
            customer.name = name.strip()

        # Update stats
        customer.purchase_count += 1
        customer.total_spent = (customer.total_spent or Decimal("0")) + Decimal(str(amount or 0))
        customer.last_purchase = timezone.now()
        customer.save()

        # Auto-earn loyalty points: 1 point per N100 spent
        try:
            _earn_loyalty_points(customer, customer.branch, amount, source)
        except Exception:
            pass  # Don't fail sale if loyalty fails
        return customer
    except Exception:
        return None


# ─────────────────────────────────────────
# FIXED record_retail_sale — captures customer name + phone
# ─────────────────────────────────────────


def _wholesale_pdf(devices, sales, user, date_from, date_to):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    BLUE = colors.HexColor("#004F9F")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    label = f"{user.username} — Wholesale Device Report"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED",
            ParagraphStyle("T", parent=styles["Heading1"], fontSize=13,
                           textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label,
            ParagraphStyle("S", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
        Paragraph("CATALOG INVENTORY",
            ParagraphStyle("H", parent=styles["Heading2"], fontSize=10,
                           textColor=BLUE, spaceBefore=8, spaceAfter=4)),
    ]

    # Inventory table
    inv_data = [["Product", "Type", "Network", "Qty", "Cost Price", "Sell Price", "Value", "Date Added"]]
    for d in devices:
        inv_data.append([
            d.product_name,
            d.get_product_type_display(),
            d.get_network_type_display(),
            str(d.quantity),
            f"N{d.cost_price:,.0f}",
            f"N{d.selling_price:,.0f}",
            f"N{d.total_value:,.0f}",
            d.date_added.strftime("%d %b %Y"),
        ])

    t1 = Table(inv_data,
               colWidths=[1.4*inch, 0.75*inch, 0.75*inch, 0.4*inch,
                          0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch],
               repeatRows=1)
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7.5),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t1)
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("SALES LOG",
        ParagraphStyle("H2", parent=styles["Heading2"], fontSize=10,
                       textColor=BLUE, spaceBefore=8, spaceAfter=4)))

    # Sales table
    sales_data = [["Date", "Time", "Product", "Buyer Type", "Buyer", "Qty", "Unit Price", "Total", "Payment"]]
    for s in sales:
        sales_data.append([
            s.date.strftime("%d %b %Y"),
            s.time.strftime("%H:%M") if s.time else "—",
            s.device.product_name,
            f"{'⭐ ' if s.is_director_sale else ''}{s.buyer_type}",
            s.buyer_name or "—",
            str(s.quantity),
            f"N{s.unit_price:,.0f}",
            f"N{s.total_amount:,.0f}",
            s.payment_method,
        ])

    t2 = Table(sales_data,
               colWidths=[0.75*inch, 0.5*inch, 1.2*inch, 0.75*inch,
                          0.9*inch, 0.4*inch, 0.75*inch, 0.8*inch, 0.65*inch],
               repeatRows=1)
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#374151")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    elements.append(t2)
    elements.append(Paragraph(
        f"Generated {timezone.now().strftime('%d %B %Y at %H:%M')} — GPSL",
        ParagraphStyle("F", parent=styles["Normal"], fontSize=7,
                       textColor=colors.grey, alignment=TA_CENTER, spaceBefore=10)
    ))

    doc.build(elements)
    buf.seek(0)
    fname = f"Wholesale_{user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buf, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ─────────────────────────────────────────
# DIRECTOR: View MultiChoice balance across all branches
# ─────────────────────────────────────────


def _build_invoice_pdf(invoice):
    """Build a professional invoice PDF using ReportLab."""
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        rightMargin=0.6*inch,
        leftMargin=0.6*inch,
        topMargin=0.6*inch,
        bottomMargin=0.6*inch,
    )

    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#004F9F")

    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=BLUE,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=BLUE,
        spaceAfter=4,
        spaceBefore=8,
    )
    normal_style = ParagraphStyle(
        'NormalCustom',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=4,
    )

    elements = []

    # Header
    elements.append(Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", title_style))
    elements.append(Paragraph("Telecom & Retail Solutions", subtitle_style))
    elements.append(Paragraph("08066090000, 08032036766, 08032036764", subtitle_style))
    elements.append(Spacer(1, 6))

    # Invoice meta
    elements.append(Paragraph(f"<b>INVOICE</b>  —  {invoice.invoice_number}", section_style))
    elements.append(Spacer(1, 4))

    meta_data = [
        ['Branch:', str(invoice.branch.name)],
        ['Address:', str(invoice.branch.full_address)],
        ['Date:', f"{invoice.date.strftime('%d %B %Y')} {invoice.time.strftime('%H:%M')}"],
        ['Payment Method:', str(invoice.payment_method or '—')],
    ]
    meta_table = Table(meta_data, colWidths=[1.8*inch, 4*inch])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0,0), (0,-1), BLUE),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8))

    # Customer info
    elements.append(Paragraph("Bill To", section_style))
    customer_lines = []
    if invoice.customer_name:
        customer_lines.append(f"Name: {invoice.customer_name}")
    if invoice.customer_phone:
        customer_lines.append(f"Phone: {invoice.customer_phone}")
    if not customer_lines:
        customer_lines.append("Walk-in Customer")

    cust_data = [[line] for line in customer_lines]
    cust_table = Table(cust_data, colWidths=[5.8*inch])
    cust_table.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
    ]))
    elements.append(cust_table)
    elements.append(Spacer(1, 12))

    # Product table
    elements.append(Paragraph("Item(s)", section_style))
    product_data = [
        ['Description', 'Qty', 'Unit Price (₦)', 'Total (₦)'],
        [
            invoice.product_description or 'Service / Product',
            str(invoice.quantity),
            f"{invoice.unit_price:,.2f}",
            f"{invoice.total_amount:,.2f}",
        ],
    ]
    product_table = Table(product_data, colWidths=[3.2*inch, 0.8*inch, 1.4*inch, 1.4*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('ALIGN', (-1,1), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,1), (0,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    elements.append(product_table)
    elements.append(Spacer(1, 8))

    # Total
    total_data = [['', '', 'Total Amount (₦):', f"{invoice.total_amount:,.2f}"]]
    total_table = Table(total_data, colWidths=[3.2*inch, 0.8*inch, 1.4*inch, 1.4*inch])
    total_table.setStyle(TableStyle([
        ('FONTNAME', (2,0), (3,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 11),
        ('TEXTCOLOR', (2,0), (3,0), BLUE),
        ('ALIGN', (2,0), (3,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 8),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 20))

    # Footer
    staff_name = invoice.staff.get_full_name() or invoice.staff.username
    elements.append(Paragraph(f"<b>Attended to by:</b> {staff_name}", normal_style))
    elements.append(Paragraph(f"<b>Branch:</b> {invoice.branch.name}", normal_style))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Thank you for your patronage. For enquiries, contact your branch manager.", subtitle_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ────────────────────────────────────────────
# MONIEPOINT POS INTEGRATION
# ────────────────────────────────────────────

