import re

print("Reading views.py...")
code = open('/home/runner/workspace/core/views.py').read()
lines = code.split('\n')

# ─────────────────────────────────────────
# FIX 1: Remove ALL old director_release_stock definitions
# Keep only the LAST one (which is the fixed version)
# ─────────────────────────────────────────

def_name = 'def director_release_stock(request):'
positions = [i for i, l in enumerate(lines) if def_name in l]
print(f"Found director_release_stock at lines: {[p+1 for p in positions]}")

if len(positions) > 1:
    # Remove all but the last definition
    for pos in reversed(positions[:-1]):
        # Find start (go back to find decorator)
        start = pos
        while start > 0 and (lines[start-1].strip().startswith('@') or lines[start-1].strip() == ''):
            start -= 1
        # Find end (next function/class at same level)
        end = pos + 1
        while end < len(lines):
            l = lines[end]
            if l and not l.startswith(' ') and not l.startswith('\t') and l.strip() and end > pos + 2:
                break
            end += 1
        print(f"Removing definition at lines {start+1}-{end}")
        lines = lines[:start] + lines[end:]
        # Recalculate positions after removal
        positions = [i for i, l in enumerate(lines) if def_name in l]

code = '\n'.join(lines)

# ─────────────────────────────────────────
# FIX 2: Also remove duplicate director_safe_stock views
# ─────────────────────────────────────────

def_name2 = 'def director_safe_stock(request):'
positions2 = [i for i, l in enumerate(lines) if def_name2 in l]
print(f"Found director_safe_stock at lines: {[p+1 for p in positions2]}")

if len(positions2) > 1:
    for pos in reversed(positions2[:-1]):
        start = pos
        while start > 0 and (lines[start-1].strip().startswith('@') or lines[start-1].strip() == ''):
            start -= 1
        end = pos + 1
        while end < len(lines):
            l = lines[end]
            if l and not l.startswith(' ') and not l.startswith('\t') and l.strip() and end > pos + 2:
                break
            end += 1
        print(f"Removing duplicate director_safe_stock at lines {start+1}-{end}")
        lines = lines[:start] + lines[end:]

code = '\n'.join(lines)
open('/home/runner/workspace/core/views.py', 'w').write(code)
print("Duplicates removed successfully")

# ─────────────────────────────────────────
# FIX 3: Add telecom activity history view
# ─────────────────────────────────────────

new_view = '''

@role_required("TELECOM")
def telecom_activity_history(request):
    from django.db.models import Sum
    date_from  = request.GET.get("date_from", "")
    date_to    = request.GET.get("date_to", "")
    stype      = request.GET.get("service_type", "")
    export     = request.GET.get("export", "")

    activities = ServiceActivity.objects.filter(
        staff=request.user
    ).select_related("branch", "device_tag").order_by("-date", "-id")

    if date_from:
        activities = activities.filter(date__gte=date_from)
    if date_to:
        activities = activities.filter(date__lte=date_to)
    if stype:
        activities = activities.filter(service_type=stype)

    total_qty = activities.filter(approved=True).aggregate(t=Sum("quantity"))["t"] or 0

    if export == "pdf":
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER
        import io as _io
        BLUE = colors.HexColor("#004F9F")
        buf = _io.BytesIO()
        doc = SimpleDocTemplate(buf, rightMargin=0.5*inch, leftMargin=0.5*inch,
                                topMargin=0.6*inch, bottomMargin=0.6*inch)
        styles = getSampleStyleSheet()
        label = f"{request.user.username} - Telecom Activity History"
        if date_from or date_to:
            label += f"  |  {date_from or 'Start'} to {date_to or 'Today'}"
        elements = [
            Paragraph("GLOBAL PHONELINZ SYSTEMS LIMITED",
                ParagraphStyle("T", parent=styles["Heading1"], fontSize=13, textColor=BLUE, alignment=TA_CENTER)),
            Paragraph(label,
                ParagraphStyle("S", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=10)),
        ]
        data = [["Date", "Service Type", "Device Tag", "Quantity", "Status", "Recorded By"]]
        for a in activities:
            data.append([
                a.date.strftime("%d %b %Y"),
                a.service_type,
                a.device_tag.tag_name if a.device_tag else "—",
                str(a.quantity),
                "Approved" if a.approved else ("Pending" if a.requires_approval else "Logged"),
                a.staff.username,
            ])
        t = Table(data, colWidths=[1*inch, 1.3*inch, 1*inch, 0.7*inch, 0.9*inch, 1.3*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), BLUE),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        elements.append(t)
        doc.build(elements)
        buf.seek(0)
        fname = f"TelecomActivity_{request.user.username}_{date_from or 'All'}_{date_to or 'Today'}.pdf".replace(" ", "_")
        from django.http import HttpResponse
        return HttpResponse(buf, content_type="application/pdf",
                            headers={"Content-Disposition": f\'attachment; filename="{fname}"\'})

    from django.core.paginator import Paginator
    paginator = Paginator(activities, 30)
    page = paginator.get_page(request.GET.get("page"))

    service_types = ServiceActivity.objects.filter(
        staff=request.user
    ).values_list("service_type", flat=True).distinct()

    return render(request, "staff/activity_history.html", {
        "activities": page,
        "total_qty": total_qty,
        "date_from": date_from,
        "date_to": date_to,
        "selected_type": stype,
        "service_types": service_types,
    })
'''

with open('/home/runner/workspace/core/views.py', 'a') as f:
    f.write(new_view)
print("Telecom activity history view added")

# ─────────────────────────────────────────
# FIX 4: Add URL for telecom activity history
# ─────────────────────────────────────────

urls_code = open('/home/runner/workspace/core/urls.py').read()
route = "    path('telecom/activity-history/', views.telecom_activity_history, name='telecom_activity_history'),"
if 'telecom_activity_history' not in urls_code:
    urls_code = urls_code.rstrip().rstrip(']').rstrip() + '\n' + route + '\n]\n'
    open('/home/runner/workspace/core/urls.py', 'w').write(urls_code)
    print("URL added")
else:
    print("URL already exists")

print("\nAll fixes applied. Now run: python manage.py check")
