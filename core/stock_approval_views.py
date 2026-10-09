"""STOCK_APPROVALS_V1

Screens for the stock approval workflow: the Pending Approvals inbox, the
approve / reject / cancel / edit actions, the Stock Audit view, and the
replacement stock actions (manager add/release, staff entries, director
release, stock transfer) that now go through core.stock_approvals.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q, Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import models as m
from core import stock_approvals as sa
from core.stock_approvals import StockError, is_director


def _back(request, default="stock_approvals"):
    return redirect(request.POST.get("next") or default)


def _fail(request, exc):
    messages.error(request, str(exc))


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def _decorate(user, reqs):
    out = []
    for r in reqs:
        r.user_can_act = sa.can_act(user, r)
        r.user_can_edit = sa.can_edit(user, r)
        out.append(r)
    return out


def _group_by_batch(reqs):
    groups, index = [], {}
    for r in reqs:
        if r.batch_ref:
            if r.batch_ref not in index:
                index[r.batch_ref] = {"batch": r.batch_ref, "items": []}
                groups.append(index[r.batch_ref])
            index[r.batch_ref]["items"].append(r)
        else:
            groups.append({"batch": "", "items": [r]})
    return groups


@login_required
def stock_approvals(request):
    user = request.user
    base = m.StockApprovalRequest.objects.select_related(
        "product", "requested_by", "from_branch", "to_branch", "from_staff", "to_staff", "approved_by", "rejected_by"
    )
    history = ("events__actor",)
    actionable = _decorate(user, list(sa.actionable_for(user).select_related(
        "product", "requested_by", "from_branch", "to_branch", "from_staff", "to_staff").prefetch_related(*history).order_by("created_at")))
    mine = _decorate(user, list(base.filter(requested_by=user, status="PENDING").prefetch_related(*history).order_by("-created_at")))
    oversight = _decorate(user, list(sa.oversight_for(user).select_related(
        "product", "requested_by", "from_branch", "to_branch", "from_staff", "to_staff").prefetch_related(*history).order_by("created_at")[:100]))

    recent_q = base.exclude(status="PENDING")
    if is_director(user):
        pass
    elif user.role == "MANAGER" and user.branch_id:
        recent_q = recent_q.filter(Q(from_branch_id=user.branch_id) | Q(to_branch_id=user.branch_id) | Q(requested_by=user))
    else:
        recent_q = recent_q.filter(Q(requested_by=user) | Q(to_staff=user) | Q(from_staff=user))
    recent = list(recent_q.prefetch_related(*history).order_by("-updated_at")[:40])

    return render(request, "stock_approvals_inbox.html", {
        "actionable_groups": _group_by_batch(actionable),
        "actionable_count": len(actionable),
        "mine": mine,
        "oversight": oversight,
        "recent": recent,
        "is_director": is_director(user),
        "can_audit": is_director(user) or user.role == "MANAGER",
    })


@login_required
@require_POST
def stock_approval_approve(request, req_id):
    try:
        req = sa.approve(req_id, request.user)
        messages.success(request, "Approved: %s." % sa._summary(req))
    except StockError as exc:
        _fail(request, exc)
    return _back(request)


@login_required
@require_POST
def stock_approval_reject(request, req_id):
    try:
        req = sa.reject(req_id, request.user, request.POST.get("reason", ""))
        extra = (" %s unit(s) could not be taken back - see Stock Audit." % req.shortfall_quantity) if req.shortfall_quantity else ""
        messages.success(request, "Rejected and the requester was told why.%s" % extra)
    except StockError as exc:
        _fail(request, exc)
    return _back(request)


@login_required
@require_POST
def stock_approval_cancel(request, req_id):
    try:
        sa.cancel(req_id, request.user)
        messages.success(request, "Request cancelled.")
    except StockError as exc:
        _fail(request, exc)
    return _back(request)


@login_required
@require_POST
def stock_approval_edit(request, req_id):
    try:
        sa.edit(req_id, request.user, quantity=request.POST.get("quantity"), note=request.POST.get("notes"))
        messages.success(request, "Request updated. The change is recorded in its history.")
    except StockError as exc:
        _fail(request, exc)
    return _back(request)


@login_required
@require_POST
def stock_approval_batch(request, batch_ref):
    action = request.POST.get("action")
    if action == "approve":
        done, failed = sa.approve_batch(batch_ref, request.user)
        messages.success(request, "Approved %s request(s)." % done)
    elif action == "reject":
        reason = request.POST.get("reason", "")
        if len(reason.strip()) < 3:
            messages.error(request, "A reason is required to reject.")
            return _back(request)
        done, failed = sa.reject_batch(batch_ref, request.user, reason)
        messages.success(request, "Rejected %s request(s)." % done)
    else:
        messages.error(request, "Unknown action.")
        return _back(request)
    for line in failed[:3]:
        messages.error(request, line)
    return _back(request)


# ---------------------------------------------------------------------------
# Stock Audit
# ---------------------------------------------------------------------------

def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def stock_audit(request):
    user = request.user
    director = is_director(user)
    if not director and not (user.role == "MANAGER" and user.branch_id):
        return HttpResponseForbidden("Only the Director and branch managers can open the stock audit.")

    g = request.GET
    branch_id = _int_or_none(g.get("branch"))
    if not director:
        branch_id = user.branch_id
    tier = g.get("tier", "")
    if not director and tier == "DIRECTOR":
        tier = ""
    staff_id = _int_or_none(g.get("staff"))
    status = g.get("status", "")
    source = g.get("source", "")
    product_q = (g.get("product") or "").strip()
    date_from = g.get("date_from", "")
    date_to = g.get("date_to", "")
    exceptions = g.get("exceptions") == "1"

    reqs = m.StockApprovalRequest.objects.select_related(
        "product", "requested_by", "from_branch", "to_branch", "from_staff", "to_staff", "approved_by", "rejected_by")
    if branch_id:
        reqs = reqs.filter(Q(from_branch_id=branch_id) | Q(to_branch_id=branch_id))
    if tier:
        reqs = reqs.filter(Q(source_tier=tier) | Q(dest_tier=tier))
    if staff_id:
        reqs = reqs.filter(Q(to_staff_id=staff_id) | Q(from_staff_id=staff_id) | Q(requested_by_id=staff_id))
    if exceptions:
        reqs = reqs.filter(Q(source_type__in=("MANUAL_DIRECTOR", "MANUAL_OTHER")) | Q(kind="ADJUST_DOWN"))
    else:
        if status in ("PENDING", "APPROVED", "REJECTED", "CANCELLED"):
            reqs = reqs.filter(status=status)
        if source in ("NORMAL", "MANUAL_DIRECTOR", "MANUAL_OTHER"):
            reqs = reqs.filter(source_type=source)
    if product_q:
        reqs = reqs.filter(Q(product__model_name__icontains=product_q) | Q(product__product_name__icontains=product_q))
    if date_from:
        reqs = reqs.filter(created_at__date__gte=date_from)
    if date_to:
        reqs = reqs.filter(created_at__date__lte=date_to)

    stale_cut = timezone.now() - timedelta(days=3)
    agg = reqs.aggregate(
        pending=Sum("quantity", filter=Q(status="PENDING")),
        rejected=Sum("quantity", filter=Q(status="REJECTED")),
        shortfall=Sum("shortfall_quantity"),
    )
    summary = {
        "total": reqs.count(),
        "pending_count": reqs.filter(status="PENDING").count(),
        "pending_units": agg["pending"] or 0,
        "stale_count": reqs.filter(status="PENDING", created_at__lt=stale_cut).count(),
        "rejected_count": reqs.filter(status="REJECTED").count(),
        "exception_count": reqs.filter(Q(source_type__in=("MANUAL_DIRECTOR", "MANUAL_OTHER")) | Q(kind="ADJUST_DOWN")).count(),
        "shortfall_units": agg["shortfall"] or 0,
        "in_transit_units": reqs.filter(kind="MOVE", status="PENDING", source_deducted=True).aggregate(t=Sum("quantity"))["t"] or 0,
    }

    page = Paginator(reqs.order_by("-created_at", "-id"), 40).get_page(g.get("page"))

    # Current holdings, filtered the same way (branch / tier / staff / product).
    holdings = []
    totals = {"DIRECTOR": 0, "BRANCH": 0, "STAFF": 0}
    value_totals = {"DIRECTOR": 0, "BRANCH": 0, "STAFF": 0}

    def product_filter(qs):
        if product_q:
            qs = qs.filter(Q(product__model_name__icontains=product_q) | Q(product__product_name__icontains=product_q))
        return qs

    if director and not branch_id and not staff_id and tier in ("", "DIRECTOR"):
        for row in product_filter(m.DirectorSafeStock.objects.filter(product__isnull=False)).values(
                "product__model_name", "product__color", "product__cost_price").annotate(qty=Sum("quantity")):
            if row["qty"]:
                holdings.append({"tier": "Director Safe", "where": "Director Safe", "product": row["product__model_name"],
                                 "color": row["product__color"], "qty": row["qty"], "value": row["qty"] * row["product__cost_price"], "key": "DIRECTOR"})
    if not staff_id and tier in ("", "BRANCH"):
        bq = m.BranchSafeStock.objects.filter(quantity__gt=0).select_related("branch", "product")
        if branch_id:
            bq = bq.filter(branch_id=branch_id)
        for row in product_filter(bq).order_by("branch__name", "product__model_name")[:500]:
            holdings.append({"tier": "Branch Safe", "where": row.branch.name, "product": row.product.model_name,
                             "color": row.product.color, "qty": row.quantity, "value": row.quantity * row.product.cost_price, "key": "BRANCH"})
    if tier in ("", "STAFF"):
        sq = m.StaffStock.objects.filter(quantity__gt=0).select_related("staff", "staff__branch", "product")
        if branch_id:
            sq = sq.filter(staff__branch_id=branch_id)
        if staff_id:
            sq = sq.filter(staff_id=staff_id)
        for row in product_filter(sq).order_by("staff__branch__name", "staff__username", "product__model_name")[:500]:
            holdings.append({"tier": "Staff Stock", "where": "%s (%s)" % (row.staff.username, row.staff.branch.name if row.staff.branch else "no branch"),
                             "product": row.product.model_name, "color": row.product.color, "qty": row.quantity,
                             "value": row.quantity * row.product.cost_price, "key": "STAFF"})
    for h in holdings:
        totals[h["key"]] += h["qty"]
        value_totals[h["key"]] += h["value"]

    staff_qs = m.User.objects.filter(role__in=sa.STAFF_ROLES).select_related("branch").order_by("branch__name", "username")
    if branch_id:
        staff_qs = staff_qs.filter(branch_id=branch_id)

    return render(request, "stock_audit.html", {
        "page": page,
        "summary": summary,
        "holdings": holdings,
        "totals": totals,
        "value_totals": value_totals,
        "grand_total_units": sum(totals.values()),
        "grand_total_value": sum(value_totals.values()),
        "branches": m.Branch.objects.all().order_by("name") if director else m.Branch.objects.filter(id=user.branch_id),
        "staff_list": staff_qs,
        "is_director": director,
        "f": {"branch": branch_id or "", "tier": tier, "staff": staff_id or "", "status": status, "source": source,
              "product": product_q, "date_from": date_from, "date_to": date_to, "exceptions": exceptions},
        "querystring": "&".join("%s=%s" % (k, v) for k, v in g.items() if k != "page" and v),
    })


# ---------------------------------------------------------------------------
# Replacement stock actions (called from thin wrappers in core/views.py)
# ---------------------------------------------------------------------------

def _qty(request, field="quantity"):
    return request.POST.get(field, "0")


def _received_from(request):
    return "MANUAL_DIRECTOR" if request.POST.get("received_from") == "DIRECTOR" else "MANUAL_OTHER"


def manager_add_stock(request):
    """Manager adds stock to the branch safe. It counts only after the Director approves."""
    if request.method == "POST":
        try:
            from core.models import RetailCategory, RetailSubCategory, RetailSubSubCategory, Product
            with transaction.atomic():
                if request.POST.get("is_new_product") == "true":
                    category = RetailCategory.objects.get(id=request.POST.get("category"))
                    subcategory, _ = RetailSubCategory.objects.get_or_create(category=category, name=request.POST.get("new_subcategory"))
                    subsub = None
                    ssname = request.POST.get("new_subsubcategory")
                    if ssname:
                        subsub, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=ssname)
                    product = Product.objects.create(
                        subcategory=subcategory, subsubcategory=subsub,
                        product_name=request.POST.get("product_name", ""),
                        model_name=request.POST.get("model_name"),
                        description=request.POST.get("description", ""),
                        imei_serial=request.POST.get("imei_serial", "") or None,
                        cost_price=float(request.POST.get("cost_price", 0)) or 0,
                        selling_price=float(request.POST.get("selling_price", 0)) or 0,
                    )
                else:
                    product = get_object_or_404(Product, id=request.POST.get("product"))
                req = sa.submit_entry(request.user, product, _qty(request), dest_tier="BRANCH",
                                      to_branch=request.user.branch, source_type="MANUAL_OTHER",
                                      note=request.POST.get("notes", ""))
            messages.success(request, "Submitted %sx %s for Director approval. It will count as branch stock once approved." % (req.quantity, product.model_name))
        except StockError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, "Error: %s" % exc)
    return redirect("manager_dashboard")


def manager_release_stock(request):
    """Manager releases branch stock to a staff member; the staff member must accept."""
    if request.method == "POST":
        try:
            branch = request.user.branch
            product = get_object_or_404(m.Product, id=request.POST.get("product"))
            staff = get_object_or_404(m.User, id=request.POST.get("staff"), branch=branch)
            req = sa.submit_move(request.user, product, _qty(request), "BRANCH", "STAFF",
                                 from_branch=branch, to_staff=staff, note=request.POST.get("notes", ""))
            messages.success(request, "Sent %sx %s to %s. It reaches their stock when they accept it." % (req.quantity, product.model_name, staff.username))
        except StockError as exc:
            messages.error(request, str(exc))
    return redirect("manager_dashboard")


def staff_create_product(request):
    """Retail staff add a product with a quantity. The quantity counts only after approval."""
    if request.method == "POST" and request.user.role == "RETAIL":
        try:
            from core.models import RetailCategory, RetailSubCategory, RetailSubSubCategory, Product
            with transaction.atomic():
                category = RetailCategory.objects.get(id=request.POST.get("category"))
                subcategory, _ = RetailSubCategory.objects.get_or_create(category=category, name=request.POST.get("new_subcategory"))
                subsub = None
                ssname = request.POST.get("new_subsubcategory")
                if ssname:
                    subsub, _ = RetailSubSubCategory.objects.get_or_create(subcategory=subcategory, name=ssname)
                product = Product.objects.create(
                    subcategory=subcategory, subsubcategory=subsub,
                    product_name=request.POST.get("product_name", ""),
                    model_name=request.POST.get("model_name"),
                    description=request.POST.get("description", ""),
                    imei_serial=request.POST.get("imei", "") or None,
                    color=request.POST.get("color", ""),
                    cost_price=0,
                    selling_price=float(request.POST.get("selling_price", 0)) or 0,
                )
                req = sa.submit_entry(request.user, product, request.POST.get("quantity", 1), dest_tier="STAFF",
                                      source_type=_received_from(request), note=request.POST.get("notes", ""))
            who = "your manager and then the Director" if req.source_type == "MANUAL_DIRECTOR" else "your manager"
            messages.success(request, "%s added. The %s unit(s) count as your stock once %s approve." % (product.model_name, req.quantity, who))
        except StockError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, "Error: %s" % exc)
    return redirect("retail_dashboard")


def staff_quantity_adjust(request, stock_id):
    """Retail staff change their own stock figure. GET shows a form (it never
    changes anything); POST records it. Increases need approval, decreases need a reason."""
    if request.user.role != "RETAIL":
        return HttpResponseForbidden()
    stock = get_object_or_404(m.StaffStock.objects.select_related("product"), id=stock_id, staff=request.user)
    raw = request.POST.get("quantity") if request.method == "POST" else request.GET.get("quantity")
    try:
        new_qty = max(int(raw), 0)
    except (TypeError, ValueError):
        messages.error(request, "Please enter a valid quantity.")
        return redirect("retail_dashboard")
    current = stock.quantity
    if new_qty == current:
        messages.info(request, "That is already your stock quantity.")
        return redirect("retail_dashboard")
    increase = new_qty > current
    diff = abs(new_qty - current)

    if request.method == "POST":
        try:
            if increase:
                req = sa.submit_entry(request.user, stock.product, diff, dest_tier="STAFF",
                                      source_type=_received_from(request), note=request.POST.get("reason", "") or "Quantity increase")
                messages.success(request, "Request to add %s unit(s) sent for approval. Your stock stays at %s until then." % (diff, current))
            else:
                sa.record_reduction(request.user, stock.product, diff, request.POST.get("reason", ""))
                messages.success(request, "Stock reduced by %s. Your manager has been told and the reason is on record." % diff)
            return redirect("retail_dashboard")
        except StockError as exc:
            messages.error(request, str(exc))

    return render(request, "stock_adjust_reason.html", {
        "stock": stock, "current": current, "new_qty": new_qty, "diff": diff, "increase": increase,
    })


def director_release(request):
    """Director releases from the Director Safe. Branch and staff releases wait for the receiver to accept."""
    if request.method == "POST":
        product_id = request.POST.get("product_id")
        release_type = request.POST.get("release_type")
        branch_id = request.POST.get("branch_id")
        staff_id = request.POST.get("staff_id")
        if not product_id:
            messages.error(request, "Please select a product.")
            return redirect("director_safe_stock")
        product = m.Product.objects.filter(id=product_id).first()
        if product is None or sa.available("DIRECTOR", product) <= 0:
            messages.error(request, "Product not found in director safe.")
            return redirect("director_safe_stock")
        try:
            qty = sa._positive(request.POST.get("quantity", 0))
            with transaction.atomic():
                if release_type == "sale":
                    sa.debit("DIRECTOR", product, qty)
                    branch = m.Branch.objects.filter(id=branch_id).first() if branch_id else None
                    desc = "Director direct sale: %sx %s. Branch: %s." % (qty, product.model_name, branch.name if branch else "N/A")
                    m.log_action(request.user, "UPDATE", "DirectorSafeStock", None, desc, request)
                    messages.success(request, "Recorded direct sale of %sx %s from director safe." % (qty, product.model_name))
                elif release_type == "branch_safe":
                    if not branch_id:
                        raise StockError("Please select a branch.")
                    branch = get_object_or_404(m.Branch, id=branch_id)
                    sa.submit_move(request.user, product, qty, "DIRECTOR", "BRANCH", to_branch=branch,
                                   note=request.POST.get("notes", ""))
                    messages.success(request, "Sent %sx %s to %s. It joins their branch safe when the Manager accepts it." % (qty, product.model_name, branch.name))
                elif release_type == "staff":
                    if not staff_id:
                        raise StockError("Please select a staff member.")
                    staff = get_object_or_404(m.User, id=staff_id)
                    sa.submit_move(request.user, product, qty, "DIRECTOR", "STAFF", to_staff=staff,
                                   note=request.POST.get("notes", ""))
                    messages.success(request, "Sent %sx %s to %s. It reaches their stock when they accept it." % (qty, product.model_name, staff.username))
                else:
                    raise StockError("Invalid release type selected.")
        except StockError as exc:
            messages.error(request, str(exc))
    return redirect("director_safe_stock")


def stock_transfer_page(request):
    """Stock Transfer page. Replaces the old version, which moved stock and then
    failed to save its record (and showed 'Transfer failed')."""
    branches = m.Branch.objects.all()
    products = m.Product.objects.all().order_by("model_name")
    staff_list = m.User.objects.filter(role__in=sa.STAFF_ROLES).order_by("username")
    if request.user.role == "MANAGER":
        staff_list = staff_list.filter(branch=request.user.branch)

    if request.method == "POST":
        try:
            transfer_type = request.POST.get("transfer_type")
            product = get_object_or_404(m.Product, id=request.POST.get("product"))
            qty = _qty(request)
            note = request.POST.get("notes", "").strip()
            from_branch = m.Branch.objects.filter(id=request.POST.get("from_branch")).first() if request.POST.get("from_branch") else None
            to_branch = m.Branch.objects.filter(id=request.POST.get("to_branch")).first() if request.POST.get("to_branch") else None
            to_staff = m.User.objects.filter(id=request.POST.get("to_staff")).first() if request.POST.get("to_staff") else None
            tiers = {
                "DIRECTOR_TO_BRANCH": ("DIRECTOR", "BRANCH"),
                "BRANCH_TO_BRANCH": ("BRANCH", "BRANCH"),
                "BRANCH_TO_STAFF": ("BRANCH", "STAFF"),
                "STAFF_TO_BRANCH": ("STAFF", "BRANCH"),
                "BRANCH_TO_DIRECTOR": ("BRANCH", "DIRECTOR"),
            }
            if transfer_type not in tiers:
                raise StockError("Please choose a transfer type.")
            src, dst = tiers[transfer_type]
            kwargs = {"note": note}
            if src == "BRANCH":
                kwargs["from_branch"] = from_branch
            if src == "STAFF":
                kwargs["from_staff"] = to_staff     # the form's staff field is the staff the stock comes FROM
            if dst == "BRANCH":
                kwargs["to_branch"] = to_branch
            if dst == "STAFF":
                kwargs["to_staff"] = to_staff
            req = sa.submit_move(request.user, product, qty, src, dst, **kwargs)
            if req.status == "APPROVED":
                messages.success(request, "Transfer complete: %sx %s moved." % (req.quantity, product.model_name))
            else:
                receiver = {"MANAGER": "the receiving Manager", "STAFF": "the staff member", "DIRECTOR": "the Director"}[req.approval_stage]
                messages.success(request, "%sx %s is on its way. It reaches the destination when %s accepts." % (req.quantity, product.model_name, receiver))
        except StockError as exc:
            messages.error(request, str(exc))
        return redirect("stock_transfer")

    transfers = m.StockTransfer.objects.select_related(
        "product", "from_branch", "to_branch", "to_staff", "initiated_by").order_by("-created_at")
    if request.user.role == "MANAGER":
        transfers = transfers.filter(Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch))
    pending = m.StockApprovalRequest.objects.filter(kind="MOVE", status="PENDING").select_related(
        "product", "from_branch", "to_branch", "from_staff", "to_staff", "requested_by").order_by("-created_at")
    if request.user.role == "MANAGER":
        pending = pending.filter(Q(from_branch=request.user.branch) | Q(to_branch=request.user.branch))
    return render(request, "stock_transfer.html", {
        "branches": branches,
        "products": products,
        "staff_list": staff_list,
        "transfers": transfers[:50],
        "pending_requests": pending[:20],
        "today": timezone.now().date(),
    })
