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

def invoice_preview(request, sale_type, sale_id):
    """Preview and manage invoice for any sale. Click-to-generate (not automatic)."""
    # Resolve the actual sale record
    if sale_type == 'RETAIL':
        sale = get_object_or_404(RetailSale, id=sale_id)
    elif sale_type == 'MULTICHOICE':
        sale = get_object_or_404(MultiChoiceSale, id=sale_id)
    elif sale_type == 'TELECOM':
        sale = get_object_or_404(ServiceActivity, id=sale_id)
    elif sale_type == 'WHOLESALE':
        sale = get_object_or_404(WholesaleDeviceSale, id=sale_id)
    else:
        return HttpResponseForbidden("Invalid sale type")

    # Permission: same branch or superuser
    if sale.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()

    # Build or retrieve invoice record
    staff = getattr(sale, 'staff', None) or getattr(sale, 'sold_by', None)
    invoice, created = Invoice.objects.get_or_create(
        sale_type=sale_type,
        sale_id=sale_id,
        defaults={
            'invoice_number': f"GPSL-{sale_type[:3].upper()}-{sale_id:06d}-{timezone.now().strftime('%Y%m%d')}",
            'branch': sale.branch,
            'staff': staff,
            'customer_name': getattr(sale, 'customer_name', '') or '',
            'customer_phone': getattr(sale, 'customer_phone', '') or '',
            'quantity': getattr(sale, 'quantity', 1) or 1,
            'unit_price': (
                getattr(sale, 'selling_price', None) or
                getattr(sale, 'amount', None) or
                getattr(sale, 'unit_price', None) or
                getattr(sale, 'price', None) or
                0
            ),
            'total_amount': (
                getattr(sale, 'total_amount', None) or
                getattr(sale, 'total_revenue', None) or
                getattr(sale, 'amount', None) or
                getattr(sale, 'price', None) or
                0
            ),
            'payment_method': getattr(sale, 'payment_method', 'CASH') or 'CASH',
        }
    )

    # Update description based on sale type
    desc = ""
    if sale_type == 'RETAIL':
        desc = f"{sale.product.model_name} ({sale.product.subcategory.name})"
    elif sale_type == 'MULTICHOICE':
        desc = f"{sale.service_type} - {sale.package_type} ({sale.get_transaction_type_display()})"
    elif sale_type == 'TELECOM':
        tag = sale.device_tag.tag_name if sale.device_tag else ""
        desc = f"{sale.service_type} {tag}".strip()
    elif sale_type == 'WHOLESALE':
        desc = f"{sale.device.product_name} ({sale.device.network_type})"

    if not invoice.product_description:
        invoice.product_description = desc
        invoice.save(update_fields=['product_description'])

    # Handle email send
    if request.method == 'POST':
        email_to = request.POST.get('email', '').strip()
        if email_to:
            try:
                pdf_buffer = _build_invoice_pdf(invoice)
                email = EmailMessage(
                    subject=f"Invoice {invoice.invoice_number} — GLOBAL PHONELINZ SYSTEMS LIMITED",
                    body=(
                        f"Dear {invoice.customer_name or 'Customer'},\n\n"
                        f"Please find attached your invoice {invoice.invoice_number}.\n\n"
                        f"Total Amount: ₦{invoice.total_amount:,.2f}\n\n"
                        f"Thank you for your business.\n\n"
                        f"Best regards,\nGLOBAL PHONELINZ SYSTEMS LIMITED"
                    ),
                    from_email=None,
                    to=[email_to],
                )
                email.attach(f"Invoice_{invoice.invoice_number}.pdf", pdf_buffer.getvalue(), 'application/pdf')
                email.send()
                invoice.emailed_to = email_to
                invoice.save(update_fields=['emailed_to'])
                messages.success(request, f"Invoice emailed to {email_to}")
            except Exception as e:
                messages.error(request, f"Failed to send email: {e}")
        return redirect('invoice_preview', sale_type=sale_type, sale_id=sale_id)

    return render(request, 'invoice_preview.html', {
        'invoice': invoice,
        'sale': sale,
        'sale_type': sale_type,
        'sale_id': sale_id,
    })


@login_required
def invoice_download_pdf(request, sale_type, sale_id):
    """Download invoice as PDF."""
    invoice = get_object_or_404(Invoice, sale_type=sale_type, sale_id=sale_id)
    if invoice.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()
    pdf_buffer = _build_invoice_pdf(invoice)
    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice_{invoice.invoice_number}.pdf"'
    return response


@login_required
def invoice_receipt(request, sale_type, sale_id):
    """Compact thermal receipt view optimized for 58mm/80mm printers and mobile."""
    invoice = get_object_or_404(Invoice, sale_type=sale_type, sale_id=sale_id)
    if invoice.branch != request.user.branch and not request.user.is_superuser:
        return HttpResponseForbidden()
    return render(request, 'invoice_receipt.html', {
        'invoice': invoice,
        'sale_type': sale_type,
        'sale_id': sale_id,
    })

