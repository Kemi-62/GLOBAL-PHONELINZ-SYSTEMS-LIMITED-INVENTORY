"""CUSTOMER_HISTORY_V1

Customer history pages: the Director's full cross-department view and the
staff department-scoped view.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from core.models import Customer
from core.utils.decorators import role_required
from core.customer_history import (
    DEPT_LABELS, DEPT_ONLINE, REAL_DEPARTMENTS,
    canonical_phone, customer_transactions, find_customer_by_phone,
    phone_key, phone_q, scope_for_user, summarize,
)


def _display_name(customer, rows, phone):
    if customer is not None and (customer.name or "").strip() and customer.name.strip().lower() != "unknown":
        return customer.name.strip()
    for r in rows:
        if r["name"]:
            return r["name"]
    return canonical_phone(phone) or phone


@role_required("DIRECTOR")
def customer_history(request, customer_id):
    """Director: everything this customer has bought, across every department.
    Read-only -- opening this page never changes stored customer totals."""
    customer = get_object_or_404(Customer, id=customer_id)
    rows = customer_transactions(customer.phone_number, departments=REAL_DEPARTMENTS)
    online_rows = customer_transactions(customer.phone_number, departments=[DEPT_ONLINE])
    summary = summarize(rows)

    written_as = sorted({r["phone"] for r in rows + online_rows if r["phone"]})
    same_number_records = []
    if phone_key(customer.phone_number):
        same_number_records = list(
            Customer.objects.filter(phone_q("phone_number", customer.phone_number))
            .exclude(id=customer.id).select_related("branch")
        )

    return render(request, "customer_history.html", {
        "customer": customer,
        "display_name": _display_name(customer, rows, customer.phone_number),
        "rows": rows,
        "online_rows": online_rows,
        "summary": summary,
        "total_spent": summary["total_spent"],
        "total_items": summary["total_items"],
        "written_as": written_as if len(written_as) > 1 else [],
        "same_number_records": same_number_records,
    })


@login_required
def my_customer_history(request):
    """Staff/Manager: this customer's transactions in the viewer's own
    department(s) and branch, from ALL staff there (so a colleague's sale is
    visible). Never shows other departments or other branches."""
    departments, branch = scope_for_user(request.user)
    if not departments:
        return HttpResponseForbidden("You do not have permission to view customer history.")

    phone = request.GET.get("phone", "").strip()
    if not phone_key(phone):
        return render(request, "my_customer_history.html", {
            "missing_phone": True, "scope_label": "",
        })

    rows = customer_transactions(phone, departments=departments, branch=branch)
    customer = find_customer_by_phone(phone)
    summary = summarize(rows)
    for r in rows:
        r["mine"] = (r["staff_id"] == request.user.id)

    if branch is None:
        scope_label = "all departments, all branches"
    else:
        names = " + ".join(DEPT_LABELS[d] for d in departments)
        scope_label = "%s at %s" % (names, branch.name)

    return render(request, "my_customer_history.html", {
        "display_name": _display_name(customer, rows, phone),
        "phone": canonical_phone(phone),
        "rows": rows,
        "summary": summary,
        "scope_label": scope_label,
        "my_count": sum(1 for r in rows if r["mine"]),
        "colleague_count": sum(1 for r in rows if not r["mine"]),
        "missing_phone": False,
    })
