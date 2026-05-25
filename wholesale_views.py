
# ─────────────────────────────────────────
# WHOLESALE DEVICE CATALOG VIEWS (Telecom Staff)
# ─────────────────────────────────────────

@role_required("TELECOM")
def wholesale_catalog(request):
    from core.models import WholesaleDevice, WholesaleDeviceSale
    branch = request.user.branch
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    export    = request.GET.get("export", "")

    devices = WholesaleDevice.objects.filter(
        branch=branch, staff=request.user
    ).order_by("-date_added")

    if date_from:
        devices = devices.filter(date_added__date__gte=date_from)
    if date_to:
        devices = devices.filter(date_added__date__lte=date_to)

    # Sales log
    sales = WholesaleDeviceSale.objects.filter(
        branch=branch, sold_by=request.user
    ).select_related("device").order_by("-created_at")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)

    total_inventory_value = sum(d.total_value for d in devices)
    total_sales_amount    = sales.aggregate(t=Sum("total_amount"))["t"] or 0
    director_sales_total  = sales.filter(
        is_director_sale=True
    ).aggregate(t=Sum("total_amount"))["t"] or 0

    if export == "pdf":
        return _wholesale_pdf(devices, sales, request.user, date_from, date_to)

    paginator_sales = Paginator(sales, 30)
    sales_page = paginator_sales.get_page(request.GET.get("sales_page"))

    return render(request, "staff/wholesale_catalog.html", {
        "devices": devices,
        "sales": sales_page,
        "total_inventory_value": total_inventory_value,
        "total_sales_amount": total_sales_amount,
        "director_sales_total": director_sales_total,
        "date_from": date_from,
        "date_to": date_to,
    })


@role_required("TELECOM")
def wholesale_add_device(request):
    from core.models import WholesaleDevice
    if request.method == "POST":
        try:
            qty   = int(request.POST.get("quantity", 0))
            cost  = Decimal(request.POST.get("cost_price") or "0")
            price = Decimal(request.POST.get("selling_price") or "0")

            with transaction.atomic():
                # Check if device already exists (same name + type + network)
                existing = WholesaleDevice.objects.filter(
                    branch=request.user.branch,
                    staff=request.user,
                    product_name__iexact=request.POST.get("product_name", "").strip(),
                    product_type=request.POST.get("product_type"),
                    network_type=request.POST.get("network_type"),
                ).first()

                if existing:
                    existing.quantity += qty
                    if cost:
                        existing.cost_price = cost
                    if price:
                        existing.selling_price = price
                    existing.save()
                    messages.success(
                        request,
                        f"Added {qty} unit(s) to existing {existing.product_name}. "
                        f"New total: {existing.quantity}."
                    )
                else:
                    WholesaleDevice.objects.create(
                        branch=request.user.branch,
                        staff=request.user,
                        product_name=request.POST.get("product_name", "").strip(),
                        product_type=request.POST.get("product_type", "MIFI"),
                        network_type=request.POST.get("network_type", "4G"),
                        serial_number=request.POST.get("serial_number", "").strip(),
                        quantity=qty,
                        cost_price=cost,
                        selling_price=price,
                        notes=request.POST.get("notes", "").strip(),
                    )
                    messages.success(
                        request,
                        f"Device added to catalog with {qty} unit(s)."
                    )
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("wholesale_catalog")


@role_required("TELECOM")
def wholesale_record_sale(request):
    from core.models import WholesaleDevice, WholesaleDeviceSale
    if request.method == "POST":
        device_id   = request.POST.get("device_id")
        qty         = int(request.POST.get("quantity", 0))
        unit_price  = Decimal(request.POST.get("unit_price") or "0")
        buyer_type  = request.POST.get("buyer_type", "CUSTOMER")
        buyer_name  = request.POST.get("buyer_name", "").strip()
        buyer_phone = request.POST.get("buyer_phone", "").strip()
        payment     = request.POST.get("payment_method", "CASH")
        notes       = request.POST.get("notes", "").strip()

        device = get_object_or_404(
            WholesaleDevice, id=device_id,
            branch=request.user.branch, staff=request.user
        )

        if qty <= 0:
            messages.error(request, "Quantity must be at least 1.")
            return redirect("wholesale_catalog")

        if qty > device.quantity:
            messages.error(
                request,
                f"Only {device.quantity} unit(s) available for {device.product_name}."
            )
            return redirect("wholesale_catalog")

        total = qty * unit_price
        is_director = buyer_type == "DIRECTOR"

        with transaction.atomic():
            device.quantity -= qty
            device.save()

            WholesaleDeviceSale.objects.create(
                device=device,
                sold_by=request.user,
                branch=request.user.branch,
                buyer_type=buyer_type,
                buyer_name=buyer_name or ("Director" if is_director else "Walk-in Customer"),
                buyer_phone=buyer_phone,
                quantity=qty,
                unit_price=unit_price,
                total_amount=total,
                payment_method=payment,
                is_director_sale=is_director,
                notes=notes,
            )

            # Save customer to CRM if phone provided
            if buyer_phone and not is_director:
                _upsert_customer(
                    phone=buyer_phone,
                    name=buyer_name,
                    branch=request.user.branch,
                    amount=total,
                    source="TELECOM",
                )

            # Audit log
            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action="CREATE",
                    model_name="WholesaleDeviceSale",
                    description=(
                        f"{'[DIRECTOR SALE] ' if is_director else ''}"
                        f"Sold {qty}x {device.product_name} ({device.network_type}) "
                        f"to {buyer_name or buyer_type} for ₦{total:,.2f}. "
                        f"Payment: {payment}."
                    ),
                )
            except Exception:
                pass

        label = "director" if is_director else buyer_name or "customer"
        messages.success(
            request,
            f"Sale recorded. {qty}x {device.product_name} sold to {label} "
            f"for ₦{total:,.2f}."
        )
    return redirect("wholesale_catalog")


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

@role_required("DIRECTOR")
def director_multichoice_balance(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")

    # Get all active weekly reports
    reports = MultiChoiceWeeklyReport.objects.select_related(
        "staff", "branch"
    ).order_by("-week_start_date")

    if branch_flt:
        reports = reports.filter(branch_id=branch_flt)
    if date_from:
        reports = reports.filter(week_start_date__gte=date_from)
    if date_to:
        reports = reports.filter(week_start_date__lte=date_to)

    # For each report, get current running balance
    report_data = []
    for r in reports:
        last_balance = MultiChoiceBalance.objects.filter(
            weekly_report=r
        ).order_by("-date", "-time").first()

        if last_balance and last_balance.balance_after_sale is not None:
            current_balance = last_balance.balance_after_sale
        else:
            current_balance = r.opening_balance + r.additional_funds

        report_data.append({
            "report": r,
            "staff": r.staff.username,
            "branch": r.branch.name,
            "week_start": r.week_start_date,
            "opening_balance": r.opening_balance,
            "additional_funds": r.additional_funds,
            "total_subscriptions": r.total_subscriptions or 0,
            "current_balance": current_balance,
            "commission": r.commission or 0,
            "is_closed": r.is_closed,
        })

    # Summary stats
    total_balance = sum(d["current_balance"] for d in report_data if not d["is_closed"])
    total_commission = sum(d["commission"] for d in report_data if d["is_closed"])
    total_subscriptions = sum(d["total_subscriptions"] for d in report_data)

    return render(request, "director/multichoice_balance.html", {
        "report_data": report_data,
        "total_balance": total_balance,
        "total_commission": total_commission,
        "total_subscriptions": total_subscriptions,
        "branches": Branch.objects.all(),
        "date_from": date_from,
        "date_to": date_to,
        "branch_flt": branch_flt,
    })
