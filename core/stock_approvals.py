"""STOCK_APPROVALS_V1

The stock approval workflow. Every rule lives here so every screen behaves the
same way:

  * MOVE   - Director Safe -> Branch Safe -> Staff Stock (and returns).
             Stock leaves the source the moment the move is requested (it is
             "in transit"), and only reaches the destination when the receiver
             accepts. A rejection or cancellation puts it back at the source.
  * ENTRY  - manual stock entry, never from a recorded release.
               staff, from Director : Manager approves (stock becomes real),
                                      then the Director confirms.
               staff, not Director  : Manager approves.
               manager              : Director approves.
             A Director rejection AFTER the manager approved takes the stock
             back out automatically; anything already sold is recorded as a
             shortfall for review.
  * Rejections need a reason, are kept for audit, never delete anything, and
    notify the person who entered the request.
  * Only the requester can edit or cancel, and only until anyone has acted.
  * Nobody can approve their own request.
"""
import uuid

from django.db import transaction
from django.utils import timezone

from core import models as m

STAFF_ROLES = ("RETAIL", "TELECOM", "MULTICHOICE")
INBOX_LINK = "/stock/approvals/"


class StockError(Exception):
    """A stock request cannot be done. The message is safe to show the user."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def batch_ref_for(request):
    """One reference per web request, so a CSV upload's rows can be approved together."""
    ref = getattr(request, "_stock_batch_ref", None)
    if not ref:
        ref = uuid.uuid4().hex[:12]
        request._stock_batch_ref = ref
    return ref


def is_director(user):
    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", "") in ("DIRECTOR", "SUPERADMIN"))


def _positive(qty):
    try:
        value = int(qty)
    except (TypeError, ValueError):
        raise StockError("Quantity must be a whole number.")
    if value <= 0:
        raise StockError("Quantity must be greater than 0.")
    return value


def _event(req, actor, action, detail=""):
    m.StockApprovalEvent.objects.create(request=req, actor=actor, action=action, detail=detail or "")


def _audit(user, action, req, text):
    try:
        m.log_action(user, action, "StockApprovalRequest", req.pk, text)
    except Exception:
        pass


def _notify(recipient, title, message, notif_type="APPROVAL"):
    try:
        if recipient is not None:
            m.notify_user(recipient, title, message, notif_type, INBOX_LINK)
    except Exception:
        pass


def _notify_role(role, title, message, branch=None, notif_type="APPROVAL"):
    try:
        m.notify_role(role, title, message, notif_type, INBOX_LINK, branch=branch)
    except Exception:
        pass


def _summary(req):
    return "%sx %s: %s" % (req.quantity, req.product.model_name, req.describe)


def _notify_stage(req, headline="Stock approval needed"):
    text = "%s requested %s" % (req.requested_by.username, _summary(req))
    if req.approval_stage == "MANAGER":
        _notify_role("MANAGER", headline, text, branch=req.to_branch)
    elif req.approval_stage == "DIRECTOR":
        _notify_role("DIRECTOR", headline, text)
    elif req.approval_stage == "STAFF":
        _notify(req.to_staff, "Stock waiting for you to accept", text)


# ---------------------------------------------------------------------------
# stock locations
# ---------------------------------------------------------------------------

def _rows(tier, product, branch=None, staff=None):
    if tier == "DIRECTOR":
        return m.DirectorSafeStock.objects.filter(product=product)
    if tier == "BRANCH":
        if branch is None:
            raise StockError("No branch was given.")
        return m.BranchSafeStock.objects.filter(branch=branch, product=product)
    if tier == "STAFF":
        if staff is None:
            raise StockError("No staff member was given.")
        return m.StaffStock.objects.filter(staff=staff, product=product)
    raise StockError("Unknown stock location.")


def _place_name(tier, branch=None, staff=None):
    if tier == "DIRECTOR":
        return "the Director Safe"
    if tier == "BRANCH":
        return "%s Branch Safe" % (branch.name if branch else "the branch")
    return "%s's stock" % (staff.username if staff else "the staff member")


def available(tier, product, branch=None, staff=None):
    """Total units at a location (the Director Safe keeps one row per addition)."""
    return sum(r.quantity for r in _rows(tier, product, branch, staff))


@transaction.atomic
def debit(tier, product, qty, branch=None, staff=None):
    rows = list(_rows(tier, product, branch, staff).select_for_update().order_by("id"))
    have = sum(r.quantity for r in rows)
    if qty > have:
        raise StockError("Only %s available in %s." % (have, _place_name(tier, branch, staff)))
    left = qty
    for row in rows:
        if left <= 0:
            break
        take = min(row.quantity, left)
        row.quantity -= take
        left -= take
        if row.quantity == 0 and tier == "DIRECTOR":
            row.delete()
        else:
            row.save(update_fields=["quantity"])


@transaction.atomic
def credit(tier, product, qty, branch=None, staff=None, note=""):
    row = _rows(tier, product, branch, staff).select_for_update().order_by("id").first()
    if row is not None:
        row.quantity += qty
        row.save(update_fields=["quantity"])
        return
    if tier == "DIRECTOR":
        m.DirectorSafeStock.objects.create(product=product, quantity=qty, notes=note)
    elif tier == "BRANCH":
        m.BranchSafeStock.objects.create(branch=branch, product=product, quantity=qty)
    else:
        m.StaffStock.objects.create(staff=staff, product=product, quantity=qty)


def _log_movement(req, actor):
    """Keep the existing Stock Movement Log in step (IN / OUT / RETURN)."""
    try:
        movement = None
        if req.kind == "MOVE":
            key = (req.source_tier, req.dest_tier)
            if key in (("DIRECTOR", "BRANCH"), ("BRANCH", "BRANCH")):
                movement = ("IN", req.to_branch)
            elif key == ("BRANCH", "STAFF"):
                movement = ("OUT", req.from_branch)
            elif key == ("DIRECTOR", "STAFF"):
                movement = ("OUT", req.to_branch)
            elif key == ("STAFF", "BRANCH"):
                movement = ("RETURN", req.to_branch)
        elif req.kind == "ENTRY":
            if req.dest_tier == "BRANCH":
                movement = ("IN", req.to_branch)
            elif req.source_type == "MANUAL_DIRECTOR":
                movement = ("OUT", req.to_branch)
        if movement and movement[1] is not None:
            m.StockMovement.objects.create(
                branch=movement[1], product=req.product, quantity=req.quantity,
                movement_type=movement[0], performed_by=req.requested_by,
            )
    except Exception:
        pass


_TRANSFER_TYPES = {
    ("DIRECTOR", "BRANCH"): "DIRECTOR_TO_BRANCH",
    ("BRANCH", "BRANCH"): "BRANCH_TO_BRANCH",
    ("BRANCH", "STAFF"): "BRANCH_TO_STAFF",
    ("STAFF", "BRANCH"): "STAFF_TO_BRANCH",
    ("BRANCH", "DIRECTOR"): "BRANCH_TO_DIRECTOR",
    ("DIRECTOR", "STAFF"): "DIRECTOR_TO_STAFF",
}


def _transfer_record(req, actor):
    """Keep the existing Stock Transfer history page in step. Only fields that
    exist on StockTransfer are used."""
    try:
        ttype = _TRANSFER_TYPES.get((req.source_tier, req.dest_tier))
        if not ttype:
            return
        note = (req.notes or "").strip()
        note = ("%s | " % note if note else "") + "Approved by %s (request #%s)" % (actor.username, req.pk)
        m.StockTransfer.objects.create(
            transfer_type=ttype, product=req.product, quantity=req.quantity, notes=note,
            from_branch=req.from_branch,
            to_branch=req.to_branch if req.dest_tier == "BRANCH" else None,
            to_staff=req.to_staff if req.dest_tier == "STAFF" else (req.from_staff if req.source_tier == "STAFF" else None),
            initiated_by=req.requested_by,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# who may do what
# ---------------------------------------------------------------------------

def can_act(user, req):
    """May this user approve or reject this request right now?"""
    if not getattr(user, "is_authenticated", False) or req.status != "PENDING":
        return False
    if user.id == req.requested_by_id:
        return False
    director = is_director(user)
    stage = req.approval_stage
    if stage == "DIRECTOR":
        return director
    if stage == "MANAGER":
        if director:
            return True
        return user.role == "MANAGER" and user.branch_id is not None and user.branch_id == req.to_branch_id
    if stage == "STAFF":
        return director or req.to_staff_id == user.id
    return False


def can_edit(user, req):
    """Only the requester, only while pending, and only before anyone has acted."""
    return (
        getattr(user, "is_authenticated", False)
        and req.requested_by_id == user.id
        and req.status == "PENDING"
        and not req.acted_on
        and req.kind != "ADJUST_DOWN"
    )


def actionable_for(user):
    """Requests waiting specifically for this user (drives the inbox and the badge)."""
    qs = m.StockApprovalRequest.objects.filter(status="PENDING").exclude(requested_by=user)
    if is_director(user):
        return qs.filter(approval_stage="DIRECTOR")
    if user.role == "MANAGER" and user.branch_id:
        return qs.filter(approval_stage="MANAGER", to_branch_id=user.branch_id)
    return qs.filter(approval_stage="STAFF", to_staff=user)


def oversight_for(user):
    """Director only: pending requests waiting on someone else."""
    if not is_director(user):
        return m.StockApprovalRequest.objects.none()
    return m.StockApprovalRequest.objects.filter(status="PENDING").exclude(approval_stage="DIRECTOR")


def pending_count(user):
    if not getattr(user, "is_authenticated", False):
        return 0
    try:
        return actionable_for(user).count()
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# submitting
# ---------------------------------------------------------------------------

def _check_move_authority(requester, source_tier, from_branch, from_staff):
    if is_director(requester):
        return
    if requester.role == "MANAGER":
        if requester.branch_id is None:
            raise StockError("Your account has no branch set.")
        if source_tier == "DIRECTOR":
            raise StockError("Only the Director can release stock from the Director Safe.")
        if source_tier == "BRANCH" and (from_branch is None or from_branch.id != requester.branch_id):
            raise StockError("You can only move stock out of your own branch.")
        if source_tier == "STAFF" and (from_staff is None or from_staff.branch_id != requester.branch_id):
            raise StockError("You can only take stock back from staff in your own branch.")
        return
    raise StockError("You are not allowed to move stock.")


def _requester_owns_destination(requester, dest_tier, to_branch):
    """The requester is the person who would otherwise have to accept: Director
    for the Director Safe, a Manager for their own branch safe. Releases TO a
    branch or staff member always need the receiver to accept."""
    if dest_tier == "DIRECTOR":
        return is_director(requester)
    if dest_tier == "BRANCH":
        return requester.role == "MANAGER" and to_branch is not None and requester.branch_id == to_branch.id
    return False


@transaction.atomic
def submit_move(requester, product, qty, source_tier, dest_tier, from_branch=None, to_branch=None,
                from_staff=None, to_staff=None, note="", batch_ref=""):
    qty = _positive(qty)
    if source_tier == dest_tier and from_branch == to_branch and from_staff == to_staff:
        raise StockError("The source and destination are the same.")
    for person in (from_staff, to_staff):
        if person is not None and person.role not in STAFF_ROLES:
            raise StockError("%s is not a staff account that can hold stock." % person.username)
    if dest_tier == "BRANCH" and to_branch is None:
        raise StockError("Please choose the destination branch.")
    if dest_tier == "STAFF" and to_staff is None:
        raise StockError("Please choose the staff member.")
    if source_tier == "BRANCH" and from_branch is None:
        raise StockError("Please choose the source branch.")
    if source_tier == "STAFF" and from_staff is None:
        raise StockError("Please choose the staff member to take stock from.")
    if source_tier == "STAFF":
        from_branch = from_staff.branch
    if dest_tier == "STAFF":
        to_branch = to_staff.branch
        if source_tier == "BRANCH" and from_branch is not None and to_staff.branch_id != from_branch.id:
            raise StockError("%s works at a different branch." % to_staff.username)

    _check_move_authority(requester, source_tier, from_branch, from_staff)

    debit(source_tier, product, qty, branch=from_branch, staff=from_staff)
    stage = {"BRANCH": "MANAGER", "STAFF": "STAFF", "DIRECTOR": "DIRECTOR"}[dest_tier]
    req = m.StockApprovalRequest.objects.create(
        kind="MOVE", source_type="NORMAL", product=product, quantity=qty,
        source_tier=source_tier, dest_tier=dest_tier,
        from_branch=from_branch, to_branch=to_branch, from_staff=from_staff, to_staff=to_staff,
        requested_by=requester, notes=(note or "").strip(), batch_ref=batch_ref or "",
        approval_stage=stage, status="PENDING", source_deducted=True,
    )
    _event(req, requester, "SUBMITTED", "%s taken from %s and held in transit" % (qty, req.source_label))
    _audit(requester, "CREATE", req, "Requested move of %s" % _summary(req))
    if _requester_owns_destination(requester, dest_tier, to_branch):
        _complete_move(req, requester, auto=True)
    else:
        _notify_stage(req)
    return req


@transaction.atomic
def submit_entry(requester, product, qty, dest_tier, to_branch=None, to_staff=None,
                 source_type="MANUAL_OTHER", note="", batch_ref=""):
    """A manual stock entry. Nothing changes until the right person approves."""
    qty = _positive(qty)
    if source_type not in ("MANUAL_DIRECTOR", "MANUAL_OTHER"):
        raise StockError("Unknown entry type.")
    if dest_tier == "STAFF":
        if requester.role not in STAFF_ROLES:
            raise StockError("Only staff can enter stock into their own stock.")
        to_staff = requester
        to_branch = requester.branch
        if to_branch is None:
            raise StockError("Your account has no branch set, so a manager cannot approve this.")
        stage = "MANAGER"
    elif dest_tier == "BRANCH":
        if requester.role != "MANAGER":
            raise StockError("Only the branch manager can enter stock into the branch safe.")
        to_branch = requester.branch
        if to_branch is None:
            raise StockError("Your account has no branch set.")
        source_type = "MANUAL_OTHER"
        stage = "DIRECTOR"
    else:
        raise StockError("Manual entries go into a branch safe or your own stock.")
    req = m.StockApprovalRequest.objects.create(
        kind="ENTRY", source_type=source_type, product=product, quantity=qty,
        source_tier="DIRECTOR" if source_type == "MANUAL_DIRECTOR" else "EXTERNAL",
        dest_tier=dest_tier, to_branch=to_branch, to_staff=to_staff,
        requested_by=requester, notes=(note or "").strip(), batch_ref=batch_ref or "",
        approval_stage=stage, status="PENDING",
    )
    _event(req, requester, "SUBMITTED", "Manual entry of %s (%s)" % (qty, req.get_source_type_display()))
    _audit(requester, "CREATE", req, "Manual stock entry %s" % _summary(req))
    _notify_stage(req)
    return req


@transaction.atomic
def record_reduction(requester, product, qty, reason):
    """Staff lowering their own stock figure. Applied at once, but a written
    reason is required, the manager is told, and it shows under Exceptions."""
    qty = _positive(qty)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StockError("Please write why the stock is being reduced.")
    if requester.role not in STAFF_ROLES:
        raise StockError("Only staff can reduce their own stock.")
    debit("STAFF", product, qty, staff=requester)
    req = m.StockApprovalRequest.objects.create(
        kind="ADJUST_DOWN", source_type="MANUAL_OTHER", product=product, quantity=qty,
        source_tier="STAFF", dest_tier="EXTERNAL", from_staff=requester, from_branch=requester.branch,
        requested_by=requester, notes=reason, approval_stage="NONE", status="APPROVED",
        source_deducted=True, stock_applied=True, approved_at=timezone.now(),
    )
    _event(req, requester, "ADJUSTED", "Reduced own stock by %s. Reason: %s" % (qty, reason))
    _audit(requester, "UPDATE", req, "Reduced own stock %sx %s. Reason: %s" % (qty, product.model_name, reason))
    if requester.branch_id:
        _notify_role("MANAGER", "Staff reduced their stock",
                     "%s removed %sx %s from their stock. Reason: %s" % (requester.username, qty, product.model_name, reason),
                     branch=requester.branch, notif_type="GENERAL")
    return req


# ---------------------------------------------------------------------------
# approving
# ---------------------------------------------------------------------------

def _locked(req_or_id):
    pk = getattr(req_or_id, "pk", req_or_id)
    try:
        return m.StockApprovalRequest.objects.select_for_update().select_related(
            "product", "requested_by", "from_branch", "to_branch", "from_staff", "to_staff"
        ).get(pk=pk)
    except m.StockApprovalRequest.DoesNotExist:
        raise StockError("That request no longer exists.")


def _complete_move(req, actor, auto=False, override=False):
    credit(req.dest_tier, req.product, req.quantity, branch=req.to_branch, staff=req.to_staff,
           note="Received (request #%s)" % req.pk)
    _log_movement(req, actor)
    now = timezone.now()
    req.status = "APPROVED"
    req.approval_stage = "NONE"
    req.stock_applied = True
    req.acted_on = True if not auto else req.acted_on
    req.approved_by = actor
    req.approved_at = now
    req.save()
    _transfer_record(req, actor)
    if auto:
        _event(req, actor, "AUTO_COMPLETED", "Requester also controls the destination, so it completed immediately")
    else:
        detail = "Accepted - %s now at %s" % (req.quantity, req.dest_label)
        if override:
            detail += " (Director acted for the receiver)"
        _event(req, actor, "APPROVED", detail)
        _notify(req.requested_by, "Stock request approved", "%s was accepted by %s." % (_summary(req), actor.username), "GENERAL")
    _audit(actor, "UPDATE", req, "Completed %s" % _summary(req))


def _finish_entry(req, actor):
    now = timezone.now()
    req.status = "APPROVED"
    req.approval_stage = "NONE"
    req.approved_by = actor
    req.approved_at = now
    req.save()
    _event(req, actor, "APPROVED", "Final approval by %s" % actor.username)
    _notify(req.requested_by, "Stock entry approved", "%s was approved by %s." % (_summary(req), actor.username), "GENERAL")


def _apply_entry_stock(req):
    credit(req.dest_tier, req.product, req.quantity, branch=req.to_branch, staff=req.to_staff,
           note="Manual entry approved (request #%s)" % req.pk)
    req.stock_applied = True
    _log_movement(req, req.requested_by)


@transaction.atomic
def approve(req_or_id, actor):
    req = _locked(req_or_id)
    if not can_act(actor, req):
        if req.status != "PENDING":
            raise StockError("This request has already been %s." % req.get_status_display().lower())
        raise StockError("You are not allowed to approve this request.")
    director = is_director(actor)
    req.acted_on = True

    if req.kind == "MOVE":
        override = director and req.approval_stage in ("MANAGER", "STAFF")
        _complete_move(req, actor, override=override)
        return req

    if req.kind != "ENTRY":
        raise StockError("This type of request does not need approval.")

    now = timezone.now()
    if req.approval_stage == "MANAGER":
        _apply_entry_stock(req)
        req.manager_approved_by = actor
        req.manager_approved_at = now
        if req.source_type == "MANUAL_DIRECTOR":
            req.approval_stage = "DIRECTOR"
            req.save()
            _event(req, actor, "MANAGER_APPROVED",
                   "Manager approved: %s now counts as %s's stock. Waiting for the Director." % (req.quantity, req.dest_label))
            if director:
                _event(req, actor, "DIRECTOR_APPROVED", "Director approved on the manager's behalf")
                _finish_entry(req, actor)
            else:
                _notify_stage(req, "Director confirmation needed")
                _notify(req.requested_by, "Stock entry approved by manager",
                        "%s is now in your stock. The Director still has to confirm it." % _summary(req), "GENERAL")
        else:
            req.save()
            _finish_entry(req, actor)
    elif req.approval_stage == "DIRECTOR":
        if not req.stock_applied:
            _apply_entry_stock(req)
        _finish_entry(req, actor)
    _audit(actor, "UPDATE", req, "Approved %s" % _summary(req))
    return req


@transaction.atomic
def reject(req_or_id, actor, reason):
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise StockError("A reason is required to reject a request.")
    req = _locked(req_or_id)
    if not can_act(actor, req):
        if req.status != "PENDING":
            raise StockError("This request has already been %s." % req.get_status_display().lower())
        raise StockError("You are not allowed to reject this request.")

    extra = ""
    if req.kind == "MOVE" and req.source_deducted and not req.stock_applied:
        credit(req.source_tier, req.product, req.quantity, branch=req.from_branch, staff=req.from_staff,
               note="Returned: request #%s rejected" % req.pk)
        extra = "%s returned to %s." % (req.quantity, req.source_label)
    elif req.kind == "ENTRY" and req.stock_applied:
        removed = min(req.quantity, available(req.dest_tier, req.product, req.to_branch, req.to_staff))
        if removed:
            debit(req.dest_tier, req.product, removed, branch=req.to_branch, staff=req.to_staff)
        req.reversed_quantity = removed
        req.shortfall_quantity = req.quantity - removed
        req.stock_applied = False
        extra = "%s taken back out of %s." % (removed, req.dest_label)
        if req.shortfall_quantity:
            extra += " SHORTFALL: %s unit(s) could not be taken back (already sold or moved) and need review." % req.shortfall_quantity

    req.status = "REJECTED"
    req.approval_stage = "NONE"
    req.acted_on = True
    req.rejected_by = actor
    req.rejected_at = timezone.now()
    req.rejection_reason = reason
    req.save()
    _event(req, actor, "REJECTED", ("Reason: %s. %s" % (reason, extra)).strip())
    _audit(actor, "UPDATE", req, "Rejected %s. Reason: %s" % (_summary(req), reason))

    message = "%s was rejected by %s. Reason: %s. %s" % (_summary(req), actor.username, reason, extra)
    _notify(req.requested_by, "Stock request rejected", message.strip(), "GENERAL")
    if req.shortfall_quantity:
        _notify_role("DIRECTOR", "Stock shortfall after rejection", message.strip(), notif_type="GENERAL")
        if req.to_branch_id:
            _notify_role("MANAGER", "Stock shortfall after rejection", message.strip(), branch=req.to_branch, notif_type="GENERAL")
    elif req.manager_approved_by_id and req.manager_approved_by_id != actor.id:
        _notify(req.manager_approved_by, "Stock you approved was rejected", message.strip(), "GENERAL")
    return req


@transaction.atomic
def cancel(req_or_id, actor):
    req = _locked(req_or_id)
    if req.requested_by_id != actor.id:
        raise StockError("Only the person who made the request can cancel it.")
    if not can_edit(actor, req):
        raise StockError("It can no longer be cancelled because it has already been acted on.")
    if req.kind == "MOVE" and req.source_deducted and not req.stock_applied:
        credit(req.source_tier, req.product, req.quantity, branch=req.from_branch, staff=req.from_staff,
               note="Returned: request #%s cancelled" % req.pk)
    req.status = "CANCELLED"
    req.approval_stage = "NONE"
    req.cancelled_at = timezone.now()
    req.save()
    _event(req, actor, "CANCELLED", "Cancelled by the requester before anyone acted")
    _audit(actor, "UPDATE", req, "Cancelled %s" % _summary(req))
    return req


@transaction.atomic
def edit(req_or_id, actor, quantity=None, note=None):
    """Requester changes quantity and/or note. Both old and new values are kept
    in the history, so nobody can quietly change a claim."""
    req = _locked(req_or_id)
    if not can_edit(actor, req):
        if req.requested_by_id != actor.id:
            raise StockError("Only the person who made the request can edit it.")
        raise StockError("It is locked because it has already been acted on.")
    changes = []
    if quantity not in (None, ""):
        new_qty = _positive(quantity)
        if new_qty != req.quantity:
            if req.kind == "MOVE" and req.source_deducted:
                delta = new_qty - req.quantity
                if delta > 0:
                    debit(req.source_tier, req.product, delta, branch=req.from_branch, staff=req.from_staff)
                else:
                    credit(req.source_tier, req.product, -delta, branch=req.from_branch, staff=req.from_staff,
                           note="Returned: request #%s reduced" % req.pk)
            changes.append("Quantity %s -> %s" % (req.quantity, new_qty))
            req.quantity = new_qty
    if note is not None and (note or "").strip() != (req.notes or "").strip():
        changes.append("Note '%s' -> '%s'" % ((req.notes or "").strip(), (note or "").strip()))
        req.notes = (note or "").strip()
    if not changes:
        return req
    req.save()
    _event(req, actor, "EDITED", "; ".join(changes))
    _audit(actor, "UPDATE", req, "Edited request #%s: %s" % (req.pk, "; ".join(changes)))
    _notify_stage(req, "Stock request was edited")
    return req


def approve_batch(batch_ref, actor):
    done, failed = 0, []
    for req in list(m.StockApprovalRequest.objects.filter(batch_ref=batch_ref, status="PENDING")):
        try:
            if can_act(actor, req):
                approve(req.pk, actor)
                done += 1
        except StockError as exc:
            failed.append("#%s: %s" % (req.pk, exc))
    return done, failed


def reject_batch(batch_ref, actor, reason):
    done, failed = 0, []
    for req in list(m.StockApprovalRequest.objects.filter(batch_ref=batch_ref, status="PENDING")):
        try:
            if can_act(actor, req):
                reject(req.pk, actor, reason)
                done += 1
        except StockError as exc:
            failed.append("#%s: %s" % (req.pk, exc))
    return done, failed
