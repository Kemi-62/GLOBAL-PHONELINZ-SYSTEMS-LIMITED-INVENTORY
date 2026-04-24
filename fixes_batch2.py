
# ─────────────────────────────────────────
# FIXED record_multichoice_sale
# Balance reduces after every subscription
# Shows running balance clearly
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
def record_multichoice_sale(request):
    if request.method == "POST":
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        weekly_report, _ = MultiChoiceWeeklyReport.objects.get_or_create(
            staff=request.user,
            branch=request.user.branch,
            week_start_date=week_start,
            defaults={"opening_balance": Decimal("0"), "additional_funds": Decimal("0")}
        )

        cost_price = Decimal(request.POST.get("cost_price") or "0")
        amount     = Decimal(request.POST.get("amount") or "0")

        # Get the most recent balance entry to find current running balance
        prev = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time").first()

        if prev and prev.balance_after_sale is not None:
            current_balance = prev.balance_after_sale
        else:
            current_balance = weekly_report.opening_balance + weekly_report.additional_funds

        # Every subscription reduces current balance by its cost price
        balance_after = current_balance - cost_price

        package_type     = request.POST.get("package_type", "")
        customer_name    = request.POST.get("customer_name", "")
        customer_phone   = request.POST.get("customer_phone", "")
        service_type     = request.POST.get("service_type", "DSTV")
        transaction_type = request.POST.get("transaction_type", "NEW")

        with transaction.atomic():
            MultiChoiceSale.objects.create(
                staff=request.user,
                branch=request.user.branch,
                customer_name=customer_name,
                customer_phone=customer_phone,
                service_type=service_type,
                package_type=package_type,
                transaction_type=transaction_type,
                cost_price=cost_price,
                amount=amount,
            )
            MultiChoiceBalance.objects.create(
                weekly_report=weekly_report,
                balance_amount=current_balance,
                balance_after_sale=balance_after,
                sale_cost_price=cost_price,
                notes=f"{service_type} — {package_type} — {customer_name}",
            )
            weekly_report.total_subscriptions = (weekly_report.total_subscriptions or Decimal("0")) + amount
            weekly_report.save(update_fields=["total_subscriptions"])

        messages.success(
            request,
            f"Sale recorded. Balance: ₦{current_balance:,.2f} → ₦{balance_after:,.2f} "
            f"(₦{cost_price:,.2f} deducted for {package_type})"
        )
    return redirect("multichoice_dashboard")


# ─────────────────────────────────────────
# FIXED multichoice_dashboard — shows current balance
# ─────────────────────────────────────────

@role_required("MULTICHOICE")
def multichoice_dashboard(request):
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    weekly_report = MultiChoiceWeeklyReport.objects.filter(
        staff=request.user, week_start_date=week_start
    ).first()

    today_sales = MultiChoiceSale.objects.filter(
        staff=request.user, date=today
    ).order_by("-time")

    search_query   = request.GET.get("search", "").strip()
    date_from      = request.GET.get("date_from", "")
    date_to        = request.GET.get("date_to", "")
    selected_month = request.GET.get("month", today.strftime("%Y-%m"))

    all_sales = MultiChoiceSale.objects.filter(staff=request.user).order_by("-date", "-time")
    if date_from:
        all_sales = all_sales.filter(date__gte=date_from)
    if date_to:
        all_sales = all_sales.filter(date__lte=date_to)
    if not date_from and not date_to and selected_month:
        yr, mo = selected_month.split("-")
        all_sales = all_sales.filter(date__year=yr, date__month=mo)
    if search_query:
        from django.db.models import Q
        all_sales = all_sales.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(package_type__icontains=search_query)
        )

    paginator = Paginator(all_sales, 30)
    all_sales_page = paginator.get_page(request.GET.get("page"))

    # Current running balance
    current_balance = None
    balance_history = None
    if weekly_report:
        last_balance = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time").first()
        if last_balance and last_balance.balance_after_sale is not None:
            current_balance = last_balance.balance_after_sale
        else:
            current_balance = weekly_report.opening_balance + weekly_report.additional_funds
        balance_history = MultiChoiceBalance.objects.filter(
            weekly_report=weekly_report
        ).order_by("-date", "-time")

    weekly_total_sales = weekly_report.total_subscriptions if weekly_report and weekly_report.is_closed else (
        weekly_report.total_subscriptions if weekly_report else 0
    )

    return render(request, "multichoice_dashboard.html", {
        "today_sales": today_sales,
        "all_sales": all_sales_page,
        "total_today": today_sales.aggregate(total=Sum("amount"))["total"] or 0,
        "weekly_report": weekly_report,
        "is_monday": today.weekday() == 0,
        "is_saturday": today.weekday() == 5,
        "weekly_total_sales": weekly_total_sales,
        "balance_history": balance_history,
        "current_balance": current_balance,
        "search_query": search_query,
        "selected_month": selected_month,
        "date_from": date_from,
        "date_to": date_to,
        "check_logs": CheckInOutLog.objects.filter(staff=request.user).order_by("-date", "-check_in_time")[:20],
    })


# ─────────────────────────────────────────
# DEVICE COMMISSION — with history
# ─────────────────────────────────────────

@role_required("MANAGER")
def add_device_commission(request):
    branch      = request.user.branch
    device_tags = DeviceTag.objects.filter(branch=branch)

    if request.method == "POST":
        DeviceTagCommission.objects.update_or_create(
            branch=branch,
            device_tag_id=request.POST.get("device_tag_id"),
            month_year=request.POST.get("month_year"),
            defaults={
                "commission_amount": request.POST.get("commission_amount"),
                "created_by": request.user,
            },
        )
        messages.success(request, "Commission recorded.")
        return redirect("add_device_commission")

    # History with filters
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    history   = DeviceTagCommission.objects.filter(branch=branch).select_related(
        "device_tag", "created_by"
    ).order_by("-created_at")
    if date_from:
        history = history.filter(created_at__date__gte=date_from)
    if date_to:
        history = history.filter(created_at__date__lte=date_to)

    paginator = Paginator(history, 30)
    history_page = paginator.get_page(request.GET.get("page"))

    total_commission = history.aggregate(t=Sum("commission_amount"))["t"] or 0

    return render(request, "device_commission_form.html", {
        "device_tags": device_tags,
        "history": history_page,
        "total_commission": total_commission,
        "date_from": date_from,
        "date_to": date_to,
    })


# ─────────────────────────────────────────
# STOCK MOVEMENT LOG — with date range + PDF download
# ─────────────────────────────────────────

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

@role_required("MULTICHOICE")
def multichoice_export_pdf(request):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER

    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    sales = MultiChoiceSale.objects.filter(staff=request.user).order_by("-date", "-time")
    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)

    buffer = io.BytesIO()
    BLUE = colors.HexColor("#004F9F")
    doc = SimpleDocTemplate(buffer, rightMargin=0.5*inch, leftMargin=0.5*inch,
                            topMargin=0.7*inch, bottomMargin=0.7*inch)
    styles = getSampleStyleSheet()

    label = f"{request.user.username} — MultiChoice Sales"
    if date_from or date_to:
        label += f"  |  {date_from or 'Start'} → {date_to or 'Today'}"

    elements = [
        Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED", ParagraphStyle("T", parent=styles["Heading1"], fontSize=14, textColor=BLUE, alignment=TA_CENTER)),
        Paragraph(label, ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)),
    ]

    total_amount = sales.aggregate(t=Sum("amount"))["t"] or 0
    total_cost   = sales.aggregate(t=Sum("cost_price"))["t"] or 0

    data = [["Date", "Customer", "Phone", "Service", "Package", "Type", "Amount", "Cost"]]
    for s in sales:
        data.append([
            s.date.strftime("%d %b %Y"),
            s.customer_name[:20],
            s.customer_phone or "—",
            s.service_type,
            s.package_type[:18],
            s.transaction_type,
            f"N{s.amount:,.0f}",
            f"N{s.cost_price:,.0f}",
        ])
    data.append(["", "", "", "", "", "TOTAL", f"N{total_amount:,.0f}", f"N{total_cost:,.0f}"])

    t = Table(data, colWidths=[0.85*inch, 1.3*inch, 0.9*inch, 0.65*inch, 1.2*inch, 0.7*inch, 0.8*inch, 0.8*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), BLUE),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#F3F4F6")),
        ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7.5),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [colors.white, colors.HexColor("#F9FAFB")]),
        ("ALIGN",         (5,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    elements.append(t)

    doc.build(elements)
    buffer.seek(0)
    fname = f"MultiChoice_{request.user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
    return HttpResponse(buffer, content_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
