# ROLES_V1
"""Screens for the newer roles: Branch Duties, Sub Director targets, Sub Director activity."""
from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import render, redirect
from django.utils import timezone

from core import models as m
from core.utils.decorators import role_required

SERVICE_TYPES = [
    ("SIM_REG", "SIM Registration"),
    ("SIM_SWAP", "SIM Swap"),
    ("SIM_UPGRADE", "SIM Upgrade"),
    ("DATA_ACTIVATION", "Data Activation"),
    ("RECHARGE", "Recharge"),
]


@role_required("BRANCH_DUTIES")
def branch_duties(request):
    """Small branch chores for people who are not a manager: expenses, daily report, device commission."""
    branch = request.user.branch
    expenses = []
    if branch:
        expenses = m.Expense.objects.filter(branch=branch).order_by("-date", "-time")[:10]
    return render(request, "branch_duties.html", {
        "branch": branch,
        "expenses": expenses,
        "categories": m.Expense.EXPENSE_CATEGORIES,
    })


@role_required("SUB_DIRECTOR", "DIRECTOR")
def set_branch_targets(request):
    """Monthly telecom targets for any branch (used where there is no manager to set them)."""
    first = date.today().replace(day=1)
    branches = m.Branch.objects.order_by("name")
    tags = m.DeviceTag.objects.select_related("branch").order_by("branch__name", "tag_name")

    if request.method == "POST":
        branch = branches.filter(id=request.POST.get("branch") or 0).first()
        service = request.POST.get("service_type", "")
        tag = None
        raw_tag = request.POST.get("device_tag") or ""
        try:
            number = int(request.POST.get("target_number", ""))
        except (TypeError, ValueError):
            number = -1
        if branch is None:
            messages.error(request, "Please choose a branch.")
        elif service not in dict(SERVICE_TYPES):
            messages.error(request, "Please choose a service type.")
        elif number < 0:
            messages.error(request, "Please enter the target as a whole number.")
        else:
            if raw_tag:
                tag = tags.filter(id=raw_tag, branch=branch).first()
                if tag is None:
                    messages.error(request, "That device tag does not belong to the chosen branch.")
                    return redirect("set_branch_targets")
            m.ServiceTarget.objects.update_or_create(
                branch=branch, service_type=service, device_tag=tag, date=first,
                defaults={"target_number": number, "created_by": request.user},
            )
            messages.success(request, "Target set for %s." % branch.name)
        return redirect("set_branch_targets")

    targets = m.ServiceTarget.objects.filter(date=first).select_related("branch", "device_tag").order_by("branch__name", "service_type")
    return render(request, "subdirector_targets.html", {
        "branches": branches, "tags": tags, "targets": targets,
        "services": SERVICE_TYPES, "month": first,
    })


@role_required("DIRECTOR")
def sub_director_activity(request):
    """Director only: everything the Sub Director(s) approved or rejected recently."""
    try:
        days = int(request.GET.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    if days not in (1, 7, 14, 30, 90):
        days = 7
    since = timezone.now() - timedelta(days=days)
    events = (m.StockApprovalEvent.objects
              .filter(actor__role="SUB_DIRECTOR", created_at__gte=since)
              .select_related("actor", "request", "request__product", "request__requested_by",
                              "request__to_branch", "request__from_branch")
              .order_by("-created_at"))
    rows = list(events[:500])
    summary = {}
    for e in rows:
        who = e.actor.username if e.actor else "(removed)"
        s = summary.setdefault(who, {"approved": 0, "rejected": 0, "requested": 0, "other": 0})
        if "APPROVED" in e.action or e.action == "AUTO_COMPLETED":
            s["approved"] += 1
        elif e.action == "REJECTED":
            s["rejected"] += 1
        elif e.action == "SUBMITTED":
            s["requested"] += 1
        else:
            s["other"] += 1
    return render(request, "director/sub_director_activity.html", {
        "rows": rows, "summary": summary, "days": days,
        "has_sub_director": m.User.objects.filter(role="SUB_DIRECTOR").exists(),
    })
