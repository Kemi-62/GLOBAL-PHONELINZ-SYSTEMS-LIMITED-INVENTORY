
# ─────────────────────────────────────────
# PASSWORD RESET FIX
# ─────────────────────────────────────────

from django.contrib.auth.views import PasswordResetConfirmView as DjPRCV

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

@role_required("DIRECTOR")
def director_safe_stock(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    export    = request.GET.get("export", "")

    stocks = DirectorSafeStock.objects.all().select_related(
        "product", "product__subcategory"
    ).order_by("-date_added")

    if date_from:
        stocks = stocks.filter(date_added__date__gte=date_from)
    if date_to:
        stocks = stocks.filter(date_added__date__lte=date_to)

    all_stocks = list(stocks)
    total_quantity = sum(s.quantity for s in all_stocks)
    total_value    = sum(s.total_value for s in all_stocks)

    if export == "pdf":
        return _director_safe_pdf(all_stocks, date_from, date_to)

    # Logs for director safe
    from core.models import AuditLog
    safe_logs = AuditLog.objects.filter(
        model_name="DirectorSafeStock"
    ).select_related("user").order_by("-timestamp")
    if date_from:
        safe_logs = safe_logs.filter(timestamp__date__gte=date_from)
    if date_to:
        safe_logs = safe_logs.filter(timestamp__date__lte=date_to)
    paginator_logs = Paginator(safe_logs, 30)
    logs_page = paginator_logs.get_page(request.GET.get("log_page"))

    return render(request, "director/director_safe.html", {
        "stocks": all_stocks,
        "products": Product.objects.all().order_by("model_name"),
        "categories": RetailCategory.objects.all(),
        "total_quantity": total_quantity,
        "total_value": total_value,
        "all_branches": Branch.objects.all(),
        "all_staff": User.objects.exclude(
            role__in=["DIRECTOR", "SUPERADMIN"]
        ).select_related("branch").order_by("branch__name", "username"),
        "safe_logs": logs_page,
        "date_from": date_from,
        "date_to": date_to,
    })


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


@role_required("DIRECTOR")
def add_director_stock(request):
    if request.method == "POST":
        try:
            product = get_object_or_404(Product, id=request.POST.get("product_id"))
            qty = int(request.POST.get("quantity", 0))
            notes = request.POST.get("notes", "")
            with transaction.atomic():
                DirectorSafeStock.objects.create(product=product, quantity=qty, notes=notes)
                try:
                    from core.models import AuditLog
                    AuditLog.objects.create(
                        user=request.user, action="CREATE",
                        model_name="DirectorSafeStock",
                        description=f"Added {qty}x {product.model_name} to director safe. Notes: {notes}",
                    )
                except Exception:
                    pass
            messages.success(request, f"Added {qty}x {product.model_name} to director safe.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("director_safe_stock")


@role_required("DIRECTOR")
def director_release_stock(request):
    if request.method == "POST":
        product_id   = request.POST.get("product_id")
        quantity     = int(request.POST.get("quantity", 0))
        release_type = request.POST.get("release_type")
        branch_id    = request.POST.get("branch_id")
        staff_id     = request.POST.get("staff_id")

        director_stock = get_object_or_404(DirectorSafeStock, product_id=product_id)

        if quantity <= 0:
            messages.error(request, "Quantity must be greater than 0.")
            return redirect("director_safe_stock")
        if quantity > director_stock.quantity:
            messages.error(request, f"Only {director_stock.quantity} unit(s) available.")
            return redirect("director_safe_stock")

        product = director_stock.product

        with transaction.atomic():
            director_stock.quantity -= quantity
            if director_stock.quantity == 0:
                director_stock.delete()
            else:
                director_stock.save()

            desc = ""
            if release_type == "sale":
                desc = f"Director sold {quantity}x {product.model_name} directly."
                messages.success(request, f"Recorded direct sale of {quantity}x {product.model_name}.")

            elif release_type == "branch_safe":
                branch = get_object_or_404(Branch, id=branch_id)
                safe_stock, _ = BranchSafeStock.objects.get_or_create(branch=branch, product_id=product_id)
                safe_stock.quantity += quantity
                safe_stock.save()
                StockMovement.objects.create(
                    branch=branch, product_id=product_id,
                    quantity=quantity, movement_type="IN", performed_by=request.user,
                )
                desc = f"Released {quantity}x {product.model_name} from director safe to {branch.name} safe."
                messages.success(request, desc)

            elif release_type == "staff":
                staff = get_object_or_404(User, id=staff_id)
                staff_stock, _ = StaffStock.objects.get_or_create(staff=staff, product_id=product_id)
                staff_stock.quantity += quantity
                staff_stock.save()
                desc = f"Released {quantity}x {product.model_name} from director safe directly to {staff.username} ({staff.branch.name if staff.branch else 'No branch'})."
                messages.success(request, desc)

            try:
                from core.models import AuditLog
                AuditLog.objects.create(
                    user=request.user, action="UPDATE",
                    model_name="DirectorSafeStock",
                    description=desc,
                )
            except Exception:
                pass
    return redirect("director_safe_stock")


# ─────────────────────────────────────────
# RETAIL SALES HISTORY — with date range + download
# ─────────────────────────────────────────

@role_required("RETAIL")
def retail_sales_history(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    product_q = request.GET.get("product", "")
    export    = request.GET.get("export", "")

    sales = RetailSale.objects.filter(
        staff=request.user
    ).select_related("product", "branch").order_by("-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if product_q:
        sales = sales.filter(product__model_name__icontains=product_q)

    total_revenue = sales.filter(is_voided=False).aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0
    total_qty = sales.filter(is_voided=False).aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        return _retail_sales_pdf(sales, request.user, date_from, date_to)

    paginator = Paginator(sales, 30)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "retail/sales_history.html", {
        "sales": page,
        "total_revenue": total_revenue,
        "total_qty": total_qty,
        "date_from": date_from,
        "date_to": date_to,
        "product_q": product_q,
    })


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

@login_required
def attendance_history(request):
    date_from = request.GET.get("date_from", "")
    date_to   = request.GET.get("date_to", "")
    export    = request.GET.get("export", "")

    qs = Attendance.objects.filter(user=request.user).order_by("-date")

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    total_late     = qs.filter(is_late=True).count()
    total_absent   = qs.filter(is_absent=True).count()
    total_deductions = qs.aggregate(t=Sum("deduction_amount"))["t"] or 0

    if export == "pdf":
        return _attendance_pdf(qs, request.user, date_from, date_to)

    paginator = Paginator(qs, 30)
    records = paginator.get_page(request.GET.get("page"))
    return render(request, "staff/attendance_history.html", {
        "records": records,
        "total_late": total_late,
        "total_absent": total_absent,
        "total_deductions": total_deductions,
        "date_from": date_from,
        "date_to": date_to,
    })


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

@role_required("DIRECTOR")
def daily_sales_report(request):
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    branch_flt = request.GET.get("branch", "")
    staff_flt  = request.GET.get("staff", "")
    export     = request.GET.get("export", "")
    today      = timezone.now().date()

    if not date_from and not date_to:
        date_from = today.isoformat()
        date_to   = today.isoformat()

    sales = RetailSale.objects.filter(
        is_voided=False
    ).select_related("product", "branch", "staff").order_by("branch__name", "-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if branch_flt:
        sales = sales.filter(branch_id=branch_flt)
    if staff_flt:
        sales = sales.filter(staff_id=staff_flt)

    total_qty     = sales.aggregate(t=Sum("quantity"))["t"] or 0
    total_revenue = sales.aggregate(t=Sum(F("quantity") * F("selling_price")))["t"] or 0

    branch_sales_summary = {}
    for s in sales:
        amt = Decimal(s.quantity) * s.selling_price
        bk  = s.branch.name
        if bk not in branch_sales_summary:
            branch_sales_summary[bk] = {"sales": [], "total_qty": 0, "total_revenue": Decimal(0)}
        branch_sales_summary[bk]["sales"].append({
            "product": s.product.model_name, "quantity": s.quantity,
            "price": s.selling_price, "amount": amt,
            "staff": s.staff.username,
            "date": s.date, "time": s.time,
        })
        branch_sales_summary[bk]["total_qty"] += s.quantity
        branch_sales_summary[bk]["total_revenue"] += amt

    if export == "pdf":
        return _director_sales_pdf(branch_sales_summary, total_qty, total_revenue, date_from, date_to)

    return render(request, "daily_sales_report.html", {
        "branch_sales_summary": branch_sales_summary,
        "total_qty": total_qty, "total_revenue": total_revenue,
        "all_branches": Branch.objects.all(),
        "all_staff": User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).order_by("username"),
        "date_from": date_from,
        "date_to": date_to,
        "selected_branch": branch_flt,
        "selected_staff": staff_flt,
        "today": today,
    })


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

@role_required("MANAGER")
def manager_sales_today(request):
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    staff_flt  = request.GET.get("staff", "")
    export     = request.GET.get("export", "")
    today      = date.today()

    # Default to today if no filter
    if not date_from and not date_to:
        date_from = today.isoformat()
        date_to   = today.isoformat()

    sales = RetailSale.objects.filter(
        branch=request.user.branch
    ).select_related("product", "staff").order_by("-date", "-time")

    if date_from:
        sales = sales.filter(date__gte=date_from)
    if date_to:
        sales = sales.filter(date__lte=date_to)
    if staff_flt:
        sales = sales.filter(staff_id=staff_flt)

    total_revenue = sales.filter(is_voided=False).aggregate(
        t=Sum(F("quantity") * F("selling_price"))
    )["t"] or 0

    if export == "pdf":
        return _retail_sales_pdf(sales, request.user, date_from, date_to)

    paginator = Paginator(sales, 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "manager/sales_today.html", {
        "sales": page,
        "total_revenue": total_revenue,
        "today": today,
        "date_from": date_from,
        "date_to": date_to,
        "staff_flt": staff_flt,
        "retail_staff": User.objects.filter(branch=request.user.branch, role="RETAIL"),
    })
