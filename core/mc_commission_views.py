"""MC_COMMISSION_V2 views."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core import mc_commission as mcc
from core import models as m
from core.utils.decorators import role_required


def _open_week(user):
    return m.MultiChoiceWeeklyReport.objects.filter(
        staff=user, branch=user.branch, is_closed=False).order_by("-id").first()


@role_required("MULTICHOICE")
def mc_balance_check(request):
    if request.method != "POST":
        return redirect("multichoice_dashboard")
    report = _open_week(request.user)
    if report is None or not mcc.needs_check(request.user, report):
        messages.info(request, "Your balance check for this week is already done.")
        return redirect("multichoice_dashboard")
    skip = (request.POST.get("skip_reason") or "").strip()
    if skip:
        mcc.record_check(request.user, report, skip_reason=skip)
        messages.warning(request, "Check skipped. The Director has been told. You can record sales now.")
        return redirect("multichoice_dashboard")
    try:
        actual = Decimal(request.POST.get("actual_balance") or "")
        if actual < 0:
            raise InvalidOperation
    except InvalidOperation:
        messages.error(request, "Enter the balance exactly as shown in the MultiChoice app.")
        return redirect("multichoice_dashboard")
    shot = request.FILES.get("screenshot")
    if not shot:
        messages.error(request, "Please attach a screenshot of the balance in the MultiChoice app.")
        return redirect("multichoice_dashboard")
    if not (getattr(shot, "content_type", "") or "").startswith("image/") or shot.size > mcc.MAX_IMAGE_BYTES:
        messages.error(request, "The screenshot must be an image under 5 MB.")
        return redirect("multichoice_dashboard")
    mcc.record_check(request.user, report, actual=actual, screenshot=shot, note=request.POST.get("note", ""))
    messages.success(request, "Balance saved. You can record sales now.")
    return redirect("multichoice_dashboard")


@role_required("DIRECTOR", "SUB_DIRECTOR")
def mc_commission_review(request):
    checks = m.MultiChoiceBalanceCheck.objects.select_related("staff", "branch", "weekly_report", "decided_by")
    pending = checks.filter(status="COMMISSION").order_by("-checked_at")
    shortages = checks.filter(status="SHORTAGE").order_by("-checked_at")
    skipped = checks.filter(status="SKIPPED").order_by("-checked_at")[:20]
    recent = checks.exclude(status__in=("COMMISSION", "SHORTAGE")).order_by("-checked_at")[:40]
    monthly = {}
    for c in checks.filter(status="COMMISSION_OK"):
        key = timezone.localtime(c.checked_at).strftime("%Y-%m")
        row = monthly.setdefault(key, {"month": key, "total": Decimal("0"), "by_staff": {}})
        row["total"] += c.difference
        row["by_staff"][c.staff.username] = row["by_staff"].get(c.staff.username, Decimal("0")) + c.difference
    months = sorted(monthly.values(), key=lambda r: r["month"], reverse=True)
    for r in months:
        r["by_staff"] = sorted(r["by_staff"].items())
    return render(request, "director/mc_commission.html", {
        "pending": pending, "shortages": shortages, "skipped": skipped, "recent": recent, "months": months,
        "tolerance": mcc.TOLERANCE,
    })


@role_required("DIRECTOR", "SUB_DIRECTOR")
def mc_commission_decide(request, pk):
    if request.method != "POST":
        return redirect("mc_commission_review")
    chk = get_object_or_404(m.MultiChoiceBalanceCheck, pk=pk)
    action = request.POST.get("action")
    note = (request.POST.get("note") or "").strip()
    if chk.status == "COMMISSION" and action in ("confirm", "reject"):
        if action == "reject" and not note:
            messages.error(request, "Please say why you are rejecting it (for example, an unrecorded top-up).")
            return redirect("mc_commission_review")
        chk.status = "COMMISSION_OK" if action == "confirm" else "REJECTED"
    elif chk.status == "SHORTAGE" and action == "review":
        chk.status = "SHORTAGE_REVIEWED"
    else:
        messages.error(request, "That entry has already been dealt with.")
        return redirect("mc_commission_review")
    chk.decided_by = request.user
    chk.decided_at = timezone.now()
    chk.decision_note = note
    chk.save()
    messages.success(request, "Saved.")
    return redirect("mc_commission_review")
