#!/usr/bin/env python3
"""
apply_stock_approvals.py  --  GPSL ERP, Issue D
================================================
Stock approval workflow: ONE inbox, ONE model, ONE audit view.

THE RULES (as you confirmed them)
  Normal chain   Director Safe -> Branch Safe (Manager accepts) -> Staff Stock
                 (staff member accepts). Stock leaves the sender at once and is
                 "in transit" until accepted; a rejection puts it back.
  Edge case 1    A staff member manually enters stock the Director handed over
                 directly. Manager approves (it becomes real staff stock and
                 shows as released in the branch log), then the Director
                 confirms. If the Director rejects AFTER that, the stock is taken
                 back out automatically; anything already sold is recorded as a
                 SHORTFALL for review.
  Edge case 2    A Manager manually enters stock that did not come from the
                 Director. Nothing counts until the Director approves.
  Rejections     Need a written reason, are kept for audit (never deleted),
                 never touch stock counts wrongly, and notify the person who
                 entered the request.
  Locking        Only the person who made a request can edit or cancel it, and
                 only until anyone has acted. Edits keep old and new values.
  No self-approval anywhere.

ALSO CHANGED (please read)
  * Staff increasing their own stock figure now needs approval; reducing it
    needs a written reason, tells the manager, and shows under Exceptions.
  * New products added by staff, and CSV bulk uploads by staff and managers,
    wait for approval (a bulk upload can be approved or rejected in one click).
  * Managers can no longer use the old /upload-stock-csv/ endpoint, which
    overwrote branch stock quantities with no record. Use Bulk Upload Stock.
  * FIXES the Stock Transfer page: in the code on GitHub it moved the stock and
    then failed to save the transfer record, showing "Transfer failed".
  * The Director Safe is totalled across all its rows (it keeps one row per
    addition, and releases used to look at only the first row).

NEW SCREENS   sidebar > Pending Approvals (with a count badge) and
              Stock Audit (Director: all branches; Manager: own branch).

NOT CHANGED (still add or move stock without approval):
  * Purchase order "Receive" (purchase_order_receive)
  * Voiding a sale (returns the units to the staff member)
  * The Director adding to the Director Safe, and the Director CSV upload
  * Telecom and MultiChoice hardware stock (separate tables)

ADDS   core/models.py (2 models) + 1 migration. The migration number is worked
       out from YOUR migrations folder when you run this, so it never clashes.
       Originals are kept as *.pre_stockappr.bak. Safe to run more than once.

RUN from the project root (next to manage.py):
    python apply_stock_approvals.py
    python manage.py makemigrations --check     # "No changes detected"
    python manage.py migrate
"""
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = "STOCK_APPROVALS_V1"

if not os.path.exists(os.path.join(BASE_DIR, "manage.py")):
    sys.exit("ERROR: run this from the project root (the folder that contains manage.py).")

MODELS_APPEND = r'''

# =============================================================================
# STOCK_APPROVALS_V1  --  unified stock approval workflow
# =============================================================================

class StockApprovalRequest(models.Model):
    """One row for every stock movement or manual stock entry that needs a
    second person's approval. Every Pending Approvals inbox, the audit view and
    every notification read from this single table."""

    KIND_CHOICES = (
        ('MOVE', 'Stock movement between locations'),
        ('ENTRY', 'Manual stock entry'),
        ('ADJUST_DOWN', 'Self-recorded reduction'),
    )
    SOURCE_CHOICES = (
        ('NORMAL', 'Normal chain release'),
        ('MANUAL_DIRECTOR', 'Manual entry - handed over by Director'),
        ('MANUAL_OTHER', 'Manual entry - not from Director'),
    )
    TIER_CHOICES = (
        ('DIRECTOR', 'Director Safe'),
        ('BRANCH', 'Branch Safe'),
        ('STAFF', 'Staff Stock'),
        ('EXTERNAL', 'Outside / other'),
    )
    STAGE_CHOICES = (
        ('MANAGER', 'Manager'),
        ('DIRECTOR', 'Director'),
        ('STAFF', 'Receiving staff'),
        ('NONE', 'Complete'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    )

    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default='MOVE')
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='NORMAL')
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='approval_requests')
    quantity = models.PositiveIntegerField()

    source_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default='EXTERNAL')
    dest_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default='EXTERNAL')
    from_branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests_out')
    to_branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests_in')
    from_staff = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests_from')
    to_staff = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests_to')

    requested_by = models.ForeignKey('User', on_delete=models.CASCADE, related_name='stock_requests_made')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, default='')
    batch_ref = models.CharField(max_length=40, blank=True, default='', db_index=True)

    approval_stage = models.CharField(max_length=10, choices=STAGE_CHOICES, default='MANAGER')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    acted_on = models.BooleanField(default=False, help_text='True once anyone other than the requester has approved or rejected it. Locks editing.')
    source_deducted = models.BooleanField(default=False, help_text='Stock was taken from the source when requested (in transit).')
    stock_applied = models.BooleanField(default=False, help_text='The destination currently holds this stock.')

    manager_approved_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_manager_approvals')
    manager_approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_final_approvals')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_rejections')
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    cancelled_at = models.DateTimeField(null=True, blank=True)

    reversed_quantity = models.PositiveIntegerField(default=0, help_text='Units taken back out of the destination after a late rejection.')
    shortfall_quantity = models.PositiveIntegerField(default=0, help_text='Units that could not be taken back because they were already sold or moved.')

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Stock Approval Request'
        verbose_name_plural = 'Stock Approval Requests'
        indexes = [
            models.Index(fields=['status', 'approval_stage']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return "#%s %sx %s (%s)" % (self.pk, self.quantity, self.product.model_name, self.status)

    @staticmethod
    def _place(tier, branch, staff):
        if tier == 'DIRECTOR':
            return 'Director Safe'
        if tier == 'BRANCH':
            return '%s Branch Safe' % (branch.name if branch else 'Branch')
        if tier == 'STAFF':
            return '%s (staff)' % (staff.username if staff else 'staff')
        return 'Outside / other'

    @property
    def source_label(self):
        if self.kind == 'ENTRY' and self.source_type == 'MANUAL_DIRECTOR':
            return 'Director (handed over directly)'
        if self.kind == 'ENTRY':
            return 'Outside (manual entry)'
        return self._place(self.source_tier, self.from_branch, self.from_staff)

    @property
    def dest_label(self):
        if self.kind == 'ADJUST_DOWN':
            return 'Removed from stock'
        return self._place(self.dest_tier, self.to_branch, self.to_staff)

    @property
    def describe(self):
        return '%s -> %s' % (self.source_label, self.dest_label)

    @property
    def is_exception(self):
        return self.kind != 'MOVE' or self.source_type != 'NORMAL'

    @property
    def in_transit(self):
        return self.kind == 'MOVE' and self.status == 'PENDING' and self.source_deducted


class StockApprovalEvent(models.Model):
    """Append-only history of what happened to a request (submitted, edited
    with old and new values, approved, rejected, cancelled, reversed)."""
    request = models.ForeignKey(StockApprovalRequest, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_approval_events')
    action = models.CharField(max_length=30)
    detail = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return '%s - %s' % (self.request_id, self.action)
'''

MIGRATION_TEMPLATE = r'''# STOCK_APPROVALS_V1 - generated with Django 5.0.x makemigrations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "__DEP__"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockApprovalRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("MOVE", "Stock movement between locations"),
                            ("ENTRY", "Manual stock entry"),
                            ("ADJUST_DOWN", "Self-recorded reduction"),
                        ],
                        default="MOVE",
                        max_length=12,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("NORMAL", "Normal chain release"),
                            (
                                "MANUAL_DIRECTOR",
                                "Manual entry - handed over by Director",
                            ),
                            ("MANUAL_OTHER", "Manual entry - not from Director"),
                        ],
                        default="NORMAL",
                        max_length=20,
                    ),
                ),
                ("quantity", models.PositiveIntegerField()),
                (
                    "source_tier",
                    models.CharField(
                        choices=[
                            ("DIRECTOR", "Director Safe"),
                            ("BRANCH", "Branch Safe"),
                            ("STAFF", "Staff Stock"),
                            ("EXTERNAL", "Outside / other"),
                        ],
                        default="EXTERNAL",
                        max_length=10,
                    ),
                ),
                (
                    "dest_tier",
                    models.CharField(
                        choices=[
                            ("DIRECTOR", "Director Safe"),
                            ("BRANCH", "Branch Safe"),
                            ("STAFF", "Staff Stock"),
                            ("EXTERNAL", "Outside / other"),
                        ],
                        default="EXTERNAL",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "batch_ref",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=40
                    ),
                ),
                (
                    "approval_stage",
                    models.CharField(
                        choices=[
                            ("MANAGER", "Manager"),
                            ("DIRECTOR", "Director"),
                            ("STAFF", "Receiving staff"),
                            ("NONE", "Complete"),
                        ],
                        default="MANAGER",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=10,
                    ),
                ),
                (
                    "acted_on",
                    models.BooleanField(
                        default=False,
                        help_text="True once anyone other than the requester has approved or rejected it. Locks editing.",
                    ),
                ),
                (
                    "source_deducted",
                    models.BooleanField(
                        default=False,
                        help_text="Stock was taken from the source when requested (in transit).",
                    ),
                ),
                (
                    "stock_applied",
                    models.BooleanField(
                        default=False,
                        help_text="The destination currently holds this stock.",
                    ),
                ),
                ("manager_approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True, default="")),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reversed_quantity",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Units taken back out of the destination after a late rejection.",
                    ),
                ),
                (
                    "shortfall_quantity",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Units that could not be taken back because they were already sold or moved.",
                    ),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_final_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "from_branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests_out",
                        to="core.branch",
                    ),
                ),
                (
                    "from_staff",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests_from",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "manager_approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_manager_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_requests",
                        to="core.product",
                    ),
                ),
                (
                    "rejected_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_rejections",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stock_requests_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "to_branch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests_in",
                        to="core.branch",
                    ),
                ),
                (
                    "to_staff",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_requests_to",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Stock Approval Request",
                "verbose_name_plural": "Stock Approval Requests",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="StockApprovalEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("action", models.CharField(max_length=30)),
                ("detail", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_approval_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="core.stockapprovalrequest",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="stockapprovalrequest",
            index=models.Index(
                fields=["status", "approval_stage"],
                name="core_stocka_status_49fa4d_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="stockapprovalrequest",
            index=models.Index(
                fields=["created_at"], name="core_stocka_created_34ab89_idx"
            ),
        ),
    ]
'''

NEW_FILES = {
    'core/stock_approvals.py': r'''"""STOCK_APPROVALS_V1

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
''',
    'core/stock_approval_views.py': r'''"""STOCK_APPROVALS_V1

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
''',
    'core/templatetags/stock_approval_tags.py': r'''"""STOCK_APPROVALS_V1 - sidebar badge: how many stock approvals are waiting for this user."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def stock_approvals_count(context):
    user = context.get("user")
    if user is None:
        request = context.get("request")
        user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return 0
    from core.stock_approvals import pending_count
    return pending_count(user)
''',
    'templates/stock_approvals_inbox.html': r'''{# STOCK_APPROVALS_V1 #}{% extends "base.html" %}
{% block content %}
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.8rem;margin-bottom:1.2rem;">
  <h1 style="font-size:1.3rem;font-weight:700;color:#004F9F;margin:0;">&#9989; Pending Approvals</h1>
  {% if can_audit %}<a href="{% url 'stock_audit' %}" class="btn-sm btn-outline">&#128269; Stock Audit</a>{% endif %}
</div>

<div class="card" style="margin-bottom:1.2rem;">
  <p class="card-title">Waiting for you ({{ actionable_count }})</p>
  {% for g in actionable_groups %}
    {% if g.batch and g.items|length > 1 %}
    <div style="border:1px dashed #9ca3af;border-radius:10px;padding:.7rem;margin-bottom:.8rem;">
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:.6rem;">
        <strong style="font-size:.85rem;">Bulk upload by {{ g.items.0.requested_by.username }} &mdash; {{ g.items|length }} items</strong>
        <form method="POST" action="{% url 'stock_approval_batch' g.batch %}">{% csrf_token %}<input type="hidden" name="action" value="approve">
          <button type="submit" class="btn-sm btn-success" onclick="return confirm('Approve all {{ g.items|length }} items?')">&#10003; Approve all</button></form>
        <form method="POST" action="{% url 'stock_approval_batch' g.batch %}" style="display:flex;gap:.4rem;">{% csrf_token %}<input type="hidden" name="action" value="reject">
          <input type="text" name="reason" placeholder="Reason to reject all" required minlength="3" style="padding:.35rem .6rem;border:1px solid #d1d5db;border-radius:6px;font-size:.8rem;">
          <button type="submit" class="btn-sm" style="background:#fee2e2;color:#b91c1c;border:1px solid #fecaca;">Reject all</button></form>
      </div>
      {% for r in g.items %}{% include "partials/stock_request_card.html" %}{% endfor %}
    </div>
    {% else %}
      {% for r in g.items %}{% include "partials/stock_request_card.html" %}{% endfor %}
    {% endif %}
  {% empty %}
  <p style="color:#9ca3af;font-size:.88rem;margin:.3rem 0;">Nothing is waiting for you.</p>
  {% endfor %}
</div>

<div class="card" style="margin-bottom:1.2rem;">
  <p class="card-title">My requests still pending ({{ mine|length }})</p>
  {% for r in mine %}{% include "partials/stock_request_card.html" %}
  {% empty %}<p style="color:#9ca3af;font-size:.88rem;margin:.3rem 0;">You have no pending requests.</p>{% endfor %}
</div>

{% if is_director %}
<div class="card" style="margin-bottom:1.2rem;">
  <p class="card-title">Waiting on others &mdash; oversight ({{ oversight|length }})</p>
  <p style="font-size:.78rem;color:#6b7280;margin:-.3rem 0 .8rem;">A backlog here is a red flag. You can act on a manager's or staff member's behalf if needed; it is recorded that you did.</p>
  {% for r in oversight %}{% include "partials/stock_request_card.html" %}
  {% empty %}<p style="color:#9ca3af;font-size:.88rem;margin:.3rem 0;">Nothing is waiting on anyone else.</p>{% endfor %}
</div>
{% endif %}

<div class="card">
  <p class="card-title">Recent decisions</p>
  {% for r in recent %}{% include "partials/stock_request_card.html" %}
  {% empty %}<p style="color:#9ca3af;font-size:.88rem;margin:.3rem 0;">No decisions yet.</p>{% endfor %}
</div>
{% endblock %}
''',
    'templates/stock_audit.html': r'''{# STOCK_APPROVALS_V1 #}{% extends "base.html" %}
{% block content %}
<style>
  .sa-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.9rem 1.1rem}
  .sa-kpi{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:.8rem 1rem;border-left:4px solid #3b82f6}
  .sa-kpi p{margin:0}.sa-kpi .l{font-size:.68rem;text-transform:uppercase;color:#6b7280}.sa-kpi .v{font-size:1.35rem;font-weight:700}
  .sa-t{width:100%;border-collapse:collapse;font-size:.82rem}
  .sa-t th{background:#f9fafb;text-align:left;padding:.55rem .7rem;border-bottom:1px solid #e5e7eb;font-weight:600;color:#374151;white-space:nowrap}
  .sa-t td{padding:.5rem .7rem;border-bottom:1px solid #f3f4f6;vertical-align:top}
  .sa-f label{display:block;font-size:.68rem;text-transform:uppercase;color:#6b7280;margin-bottom:.2rem}
  .sa-f select,.sa-f input{padding:.4rem .5rem;border:1px solid #d1d5db;border-radius:6px;font-size:.82rem;width:100%;box-sizing:border-box}
  .pill{border-radius:999px;padding:.1rem .55rem;font-size:.68rem;font-weight:700;white-space:nowrap}
</style>

<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.8rem;margin-bottom:1rem;">
  <h1 style="font-size:1.3rem;font-weight:700;color:#004F9F;margin:0;">&#128269; Stock Audit</h1>
  <a href="{% url 'stock_approvals' %}" class="btn-sm btn-outline">&larr; Pending Approvals</a>
</div>

<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:1rem;">
  <a href="?exceptions=1{% if f.branch and is_director %}&branch={{ f.branch }}{% endif %}" class="btn-sm" style="{% if f.exceptions %}background:#b45309;color:#fff;{% else %}background:#fef3c7;color:#92400e;border:1px solid #fcd34d;{% endif %}">&#9888;&#65039; Exceptions ({{ summary.exception_count }}) &mdash; every manual / bypass entry, any status</a>
  <a href="?status=PENDING" class="btn-sm btn-outline">Pending only</a>
  <a href="?status=REJECTED" class="btn-sm btn-outline">Rejected only</a>
  <a href="{% url 'stock_audit' %}" class="btn-sm btn-outline">Clear all filters</a>
</div>

<form method="GET" class="sa-card sa-f" style="margin-bottom:1rem;">
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;">
    <div><label>Branch</label>
      <select name="branch" {% if not is_director %}disabled{% endif %}>
        {% if is_director %}<option value="">All branches</option>{% endif %}
        {% for b in branches %}<option value="{{ b.id }}" {% if f.branch == b.id %}selected{% endif %}>{{ b.name }}</option>{% endfor %}
      </select></div>
    <div><label>Tier</label>
      <select name="tier"><option value="">All tiers</option>
        {% if is_director %}<option value="DIRECTOR" {% if f.tier == 'DIRECTOR' %}selected{% endif %}>Director Safe</option>{% endif %}
        <option value="BRANCH" {% if f.tier == 'BRANCH' %}selected{% endif %}>Branch Safe</option>
        <option value="STAFF" {% if f.tier == 'STAFF' %}selected{% endif %}>Staff Stock</option></select></div>
    <div><label>Staff member</label>
      <select name="staff"><option value="">All staff</option>
        {% for s in staff_list %}<option value="{{ s.id }}" {% if f.staff == s.id %}selected{% endif %}>{{ s.username }}{% if s.branch %} ({{ s.branch.name }}){% endif %}</option>{% endfor %}</select></div>
    <div><label>Status</label>
      <select name="status"><option value="">Any status</option>
        <option value="PENDING" {% if f.status == 'PENDING' %}selected{% endif %}>Pending approval</option>
        <option value="APPROVED" {% if f.status == 'APPROVED' %}selected{% endif %}>Approved</option>
        <option value="REJECTED" {% if f.status == 'REJECTED' %}selected{% endif %}>Rejected</option>
        <option value="CANCELLED" {% if f.status == 'CANCELLED' %}selected{% endif %}>Cancelled</option></select></div>
    <div><label>Source type</label>
      <select name="source"><option value="">All sources</option>
        <option value="NORMAL" {% if f.source == 'NORMAL' %}selected{% endif %}>Normal chain release</option>
        <option value="MANUAL_DIRECTOR" {% if f.source == 'MANUAL_DIRECTOR' %}selected{% endif %}>Manual - from Director</option>
        <option value="MANUAL_OTHER" {% if f.source == 'MANUAL_OTHER' %}selected{% endif %}>Manual - not from Director</option></select></div>
    <div><label>Item / product</label><input type="text" name="product" value="{{ f.product }}" placeholder="Model name"></div>
    <div><label>From date</label><input type="date" name="date_from" value="{{ f.date_from }}"></div>
    <div><label>To date</label><input type="date" name="date_to" value="{{ f.date_to }}"></div>
  </div>
  {% if not is_director %}<input type="hidden" name="branch" value="{{ f.branch }}">{% endif %}
  <div style="margin-top:.8rem;display:flex;gap:.5rem;"><button type="submit" class="btn-sm btn-primary">Apply filters</button>
    {% if f.exceptions %}<span style="font-size:.78rem;color:#b45309;align-self:center;">Exceptions mode: status and source filters are ignored so nothing is hidden.</span>{% endif %}</div>
</form>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin-bottom:1rem;">
  <div class="sa-kpi" style="border-left-color:#f59e0b;"><p class="l">Pending approval</p><p class="v">{{ summary.pending_count }}</p><p style="font-size:.72rem;color:#6b7280;">{{ summary.pending_units }} unit(s)</p></div>
  <div class="sa-kpi" style="border-left-color:{% if summary.stale_count %}#dc2626{% else %}#10b981{% endif %};"><p class="l">Pending over 3 days</p><p class="v" style="{% if summary.stale_count %}color:#dc2626;{% endif %}">{{ summary.stale_count }}</p><p style="font-size:.72rem;color:#6b7280;">backlog = red flag</p></div>
  <div class="sa-kpi" style="border-left-color:#8b5cf6;"><p class="l">In transit</p><p class="v">{{ summary.in_transit_units }}</p><p style="font-size:.72rem;color:#6b7280;">unit(s) not yet accepted</p></div>
  <div class="sa-kpi" style="border-left-color:#ef4444;"><p class="l">Rejected</p><p class="v">{{ summary.rejected_count }}</p></div>
  <div class="sa-kpi" style="border-left-color:#b45309;"><p class="l">Exceptions</p><p class="v">{{ summary.exception_count }}</p></div>
  <div class="sa-kpi" style="border-left-color:{% if summary.shortfall_units %}#dc2626{% else %}#10b981{% endif %};"><p class="l">Shortfall units</p><p class="v" style="{% if summary.shortfall_units %}color:#dc2626;{% endif %}">{{ summary.shortfall_units }}</p></div>
</div>

<div class="sa-card" style="margin-bottom:1rem;">
  <p style="font-weight:700;margin:0 0 .2rem;">Current stock held (approved stock only)</p>
  <p style="font-size:.76rem;color:#6b7280;margin:0 0 .7rem;">Respects the branch, tier, staff and product filters. Company-wide total = no branch filter, tier = all.</p>
  <div style="display:flex;gap:1.2rem;flex-wrap:wrap;font-size:.84rem;margin-bottom:.7rem;">
    <span>Director Safe: <strong>{{ totals.DIRECTOR }}</strong> (&#8358;{{ value_totals.DIRECTOR|floatformat:0 }})</span>
    <span>Branch Safes: <strong>{{ totals.BRANCH }}</strong> (&#8358;{{ value_totals.BRANCH|floatformat:0 }})</span>
    <span>Staff Stock: <strong>{{ totals.STAFF }}</strong> (&#8358;{{ value_totals.STAFF|floatformat:0 }})</span>
    <span style="font-weight:700;">Total: {{ grand_total_units }} unit(s) &middot; &#8358;{{ grand_total_value|floatformat:0 }} at cost</span>
  </div>
  <div style="overflow-x:auto;max-height:340px;overflow-y:auto;">
    <table class="sa-t"><thead><tr><th>Tier</th><th>Where</th><th>Product</th><th style="text-align:right;">Qty</th><th style="text-align:right;">Value at cost</th></tr></thead><tbody>
      {% for h in holdings %}<tr><td>{{ h.tier }}</td><td>{{ h.where }}</td><td>{{ h.product }}{% if h.color %} <span style="color:#9ca3af;">({{ h.color }})</span>{% endif %}</td><td style="text-align:right;">{{ h.qty }}</td><td style="text-align:right;">&#8358;{{ h.value|floatformat:0 }}</td></tr>
      {% empty %}<tr><td colspan="5" style="text-align:center;color:#9ca3af;padding:1.2rem;">No stock matches these filters.</td></tr>{% endfor %}
    </tbody></table>
  </div>
</div>

<div class="sa-card">
  <p style="font-weight:700;margin:0 0 .2rem;">Entries and movements ({{ summary.total }})</p>
  <p style="font-size:.76rem;color:#6b7280;margin:0 0 .7rem;">Every approval request, including rejected and cancelled ones, newest first. Dated by when it was requested.</p>
  <div style="overflow-x:auto;">
    <table class="sa-t"><thead><tr><th>Date</th><th>Product</th><th style="text-align:right;">Qty</th><th>From &rarr; To</th><th>Source</th><th>Requested by</th><th>Status</th><th>Decided by</th></tr></thead><tbody>
      {% for r in page %}
      <tr {% if r.shortfall_quantity %}style="background:#fef2f2;"{% endif %}>
        <td style="white-space:nowrap;color:#6b7280;">{{ r.created_at|date:"d M Y H:i" }}</td>
        <td><strong>{{ r.product.model_name }}</strong>{% if r.product.color %} <span style="color:#9ca3af;">({{ r.product.color }})</span>{% endif %}</td>
        <td style="text-align:right;">{{ r.quantity }}</td>
        <td>{{ r.source_label }} &rarr; {{ r.dest_label }}{% if r.notes %}<br><span style="font-size:.72rem;color:#9ca3af;">&ldquo;{{ r.notes }}&rdquo;</span>{% endif %}</td>
        <td>{% if r.source_type == 'NORMAL' %}<span class="pill" style="background:#f3f4f6;color:#374151;">Normal</span>{% else %}<span class="pill" style="background:#fef3c7;color:#92400e;">{% if r.kind == 'ADJUST_DOWN' %}Reduction{% elif r.source_type == 'MANUAL_DIRECTOR' %}Manual - Director{% else %}Manual - other{% endif %}</span>{% endif %}</td>
        <td>{{ r.requested_by.username }}</td>
        <td><span class="pill" style="{% if r.status == 'APPROVED' %}background:#dcfce7;color:#166534;{% elif r.status == 'REJECTED' %}background:#fee2e2;color:#991b1b;{% elif r.status == 'PENDING' %}background:#fef3c7;color:#92400e;{% else %}background:#f3f4f6;color:#6b7280;{% endif %}">{{ r.get_status_display }}</span>
          {% if r.status == 'PENDING' %}<br><span style="font-size:.7rem;color:#9ca3af;">at {{ r.get_approval_stage_display }}</span>{% endif %}
          {% if r.shortfall_quantity %}<br><span style="font-size:.7rem;color:#b91c1c;font-weight:700;">shortfall {{ r.shortfall_quantity }}</span>{% endif %}</td>
        <td style="font-size:.78rem;">{% if r.status == 'REJECTED' %}{{ r.rejected_by.username|default:"-" }}<br><span style="color:#b91c1c;">{{ r.rejection_reason }}</span>{% elif r.approved_by %}{{ r.approved_by.username }}{% else %}&mdash;{% endif %}</td>
      </tr>
      {% empty %}<tr><td colspan="8" style="text-align:center;color:#9ca3af;padding:1.5rem;">No entries match these filters.</td></tr>{% endfor %}
    </tbody></table>
  </div>
  {% if page.paginator.num_pages > 1 %}
  <div style="display:flex;gap:.6rem;justify-content:center;margin-top:.8rem;font-size:.82rem;">
    {% if page.has_previous %}<a href="?{{ querystring }}&page={{ page.previous_page_number }}">&larr; Newer</a>{% endif %}
    <span>Page {{ page.number }} of {{ page.paginator.num_pages }}</span>
    {% if page.has_next %}<a href="?{{ querystring }}&page={{ page.next_page_number }}">Older &rarr;</a>{% endif %}
  </div>
  {% endif %}
</div>
{% endblock %}
''',
    'templates/stock_adjust_reason.html': r'''{# STOCK_APPROVALS_V1 #}{% extends "base.html" %}
{% block content %}
<div style="max-width:520px;margin:0 auto;">
  <h1 style="font-size:1.25rem;font-weight:700;color:#004F9F;margin:0 0 1rem;">{% if increase %}Add to my stock{% else %}Reduce my stock{% endif %}</h1>
  <div class="card">
    <p style="margin:0 0 .3rem;"><strong>{{ stock.product.model_name }}</strong>{% if stock.product.color %} ({{ stock.product.color }}){% endif %}</p>
    <p style="margin:0 0 1rem;font-size:.9rem;">Your stock: <strong>{{ current }}</strong> &rarr; <strong>{{ new_qty }}</strong> ({% if increase %}+{% else %}&minus;{% endif %}{{ diff }})</p>
    <form method="POST" action="{% url 'edit_staff_stock_quantity' stock.id %}">{% csrf_token %}
      <input type="hidden" name="quantity" value="{{ new_qty }}">
      {% if increase %}
      <div class="form-group"><label>Where did this extra stock come from? *</label>
        <select name="received_from" required>
          <option value="OTHER">My branch manager / a supplier</option>
          <option value="DIRECTOR">The Director, directly to me</option>
        </select></div>
      <div class="form-group"><label>Note (what is this stock?) *</label>
        <input type="text" name="reason" required minlength="3" placeholder="e.g. 3 more units received today"></div>
      <p style="font-size:.78rem;color:#6b7280;">Your stock stays at {{ current }} until your manager approves this. You can change or cancel it from Pending Approvals until someone acts on it.</p>
      {% else %}
      <div class="form-group"><label>Why is your stock being reduced? *</label>
        <textarea name="reason" required minlength="3" rows="3" placeholder="e.g. returned 2 units to the manager, 1 damaged"></textarea></div>
      <p style="font-size:.78rem;color:#b45309;">This takes effect immediately, your manager is told, and the reason is kept on record. Units that were sold must be recorded as sales, not removed here.</p>
      {% endif %}
      <div style="display:flex;gap:.6rem;margin-top:1rem;">
        <button type="submit" class="btn-sm btn-primary">{% if increase %}Send for approval{% else %}Reduce stock{% endif %}</button>
        <a href="{% url 'retail_dashboard' %}" class="btn-sm btn-outline">Cancel</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
''',
    'templates/partials/stock_request_card.html': r'''{# STOCK_APPROVALS_V1 #}
<div style="border:1px solid #e5e7eb;border-radius:10px;padding:.9rem 1rem;margin-bottom:.7rem;background:#fff;{% if r.kind != 'MOVE' %}border-left:4px solid #f59e0b;{% endif %}">
  <div style="display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap;align-items:flex-start;">
    <div>
      <strong style="font-size:1rem;">{{ r.quantity }}&times; {{ r.product.model_name }}{% if r.product.color %} <span style="color:#6b7280;font-weight:400;">({{ r.product.color }})</span>{% endif %}</strong>
      <div style="font-size:.8rem;color:#374151;margin-top:.15rem;">{{ r.source_label }} &rarr; {{ r.dest_label }}</div>
    </div>
    <div style="display:flex;gap:.3rem;flex-wrap:wrap;">
      <span style="background:#eff6ff;color:#1d4ed8;border-radius:999px;padding:.12rem .6rem;font-size:.7rem;font-weight:700;">{{ r.get_kind_display }}</span>
      {% if r.status == 'PENDING' %}<span style="background:#fef3c7;color:#92400e;border-radius:999px;padding:.12rem .6rem;font-size:.7rem;font-weight:700;">Waiting for {{ r.get_approval_stage_display }}</span>{% endif %}
      {% if r.in_transit %}<span style="background:#ede9fe;color:#5b21b6;border-radius:999px;padding:.12rem .6rem;font-size:.7rem;font-weight:700;">In transit</span>{% endif %}
      {% if r.stock_applied and r.status == 'PENDING' %}<span style="background:#dcfce7;color:#166534;border-radius:999px;padding:.12rem .6rem;font-size:.7rem;font-weight:700;">Already counted in stock</span>{% endif %}
    </div>
  </div>
  <div style="font-size:.76rem;color:#6b7280;margin-top:.35rem;">
    Requested by <strong>{{ r.requested_by.username }}</strong> &middot; {{ r.created_at|date:"d M Y H:i" }}
    {% if r.get_source_type_display and r.source_type != 'NORMAL' %}&middot; <span style="color:#b45309;">{{ r.get_source_type_display }}</span>{% endif %}
  </div>
  {% if r.notes %}<div style="font-size:.8rem;margin-top:.35rem;background:#f9fafb;border-radius:6px;padding:.4rem .6rem;">&ldquo;{{ r.notes }}&rdquo;</div>{% endif %}

  {% if r.user_can_act %}
  <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.7rem;align-items:center;">
    <form method="POST" action="{% url 'stock_approval_approve' r.id %}">{% csrf_token %}
      <button type="submit" class="btn-sm btn-success" onclick="return confirm('Approve {{ r.quantity }} x {{ r.product.model_name|escapejs }}?')">&#10003; {% if r.kind == 'MOVE' %}Accept{% else %}Approve{% endif %}</button>
    </form>
    <form method="POST" action="{% url 'stock_approval_reject' r.id %}" style="display:flex;gap:.4rem;flex:1;min-width:220px;">{% csrf_token %}
      <input type="text" name="reason" placeholder="Reason for rejecting (required)" required minlength="3" style="flex:1;padding:.4rem .6rem;border:1px solid #d1d5db;border-radius:6px;font-size:.82rem;">
      <button type="submit" class="btn-sm" style="background:#fee2e2;color:#b91c1c;border:1px solid #fecaca;">Reject</button>
    </form>
  </div>
  {% endif %}

  {% if r.user_can_edit %}
  <details style="margin-top:.6rem;">
    <summary style="cursor:pointer;font-size:.78rem;color:#004F9F;">Edit or cancel my request</summary>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;align-items:center;">
      <form method="POST" action="{% url 'stock_approval_edit' r.id %}" style="display:flex;gap:.4rem;flex-wrap:wrap;">{% csrf_token %}
        <input type="number" name="quantity" min="1" value="{{ r.quantity }}" style="width:90px;padding:.4rem .5rem;border:1px solid #d1d5db;border-radius:6px;">
        <input type="text" name="notes" value="{{ r.notes }}" placeholder="Note" style="min-width:180px;padding:.4rem .6rem;border:1px solid #d1d5db;border-radius:6px;">
        <button type="submit" class="btn-sm btn-primary">Save</button>
      </form>
      <form method="POST" action="{% url 'stock_approval_cancel' r.id %}">{% csrf_token %}
        <button type="submit" class="btn-sm btn-outline" onclick="return confirm('Cancel this request?')">Cancel request</button>
      </form>
    </div>
    <p style="font-size:.7rem;color:#9ca3af;margin:.3rem 0 0;">You can change or cancel it only until someone acts on it. Every change is recorded.</p>
  </details>
  {% elif r.status == 'PENDING' and r.requested_by_id == request.user.id and r.acted_on %}
  <p style="font-size:.72rem;color:#9ca3af;margin:.5rem 0 0;">&#128274; Locked: someone has already acted on this request.</p>
  {% endif %}

  {% if r.status == 'REJECTED' %}
  <div style="margin-top:.5rem;font-size:.8rem;color:#b91c1c;background:#fef2f2;border-radius:6px;padding:.4rem .6rem;">
    Rejected by {{ r.rejected_by.username|default:"-" }}: {{ r.rejection_reason }}
    {% if r.reversed_quantity %}<br>{{ r.reversed_quantity }} unit(s) taken back out of stock.{% endif %}
    {% if r.shortfall_quantity %}<br><strong>Shortfall: {{ r.shortfall_quantity }} unit(s) were already sold or moved and could not be taken back.</strong>{% endif %}
  </div>
  {% endif %}

  {% if r.events.all %}
  <details style="margin-top:.5rem;">
    <summary style="cursor:pointer;font-size:.74rem;color:#6b7280;">History ({{ r.events.all|length }})</summary>
    <ul style="margin:.4rem 0 0;padding-left:1.1rem;font-size:.74rem;color:#4b5563;">
      {% for e in r.events.all %}<li><strong>{{ e.action }}</strong> &middot; {{ e.actor.username|default:"system" }} &middot; {{ e.created_at|date:"d M H:i" }}{% if e.detail %}<br><span style="color:#6b7280;">{{ e.detail }}</span>{% endif %}</li>{% endfor %}
    </ul>
  </details>
  {% endif %}
</div>
''',
}

# =========================================================================
# Patches to existing files
# =========================================================================

# function name -> (delegate call, text the OLD body must contain)
FUNCTION_DELEGATES = {
    "add_stock_to_safe": ("manager_add_stock(request)", "BranchSafeStock"),
    "release_stock": ("manager_release_stock(request)", "StaffStock"),
    "staff_create_product": ("staff_create_product(request)", "StaffStock"),
    "edit_staff_stock_quantity": ("staff_quantity_adjust(request, stock_id)", "stock.quantity"),
    "director_release_stock": ("director_release(request)", "DirectorSafeStock"),
    "stock_transfer": ("stock_transfer_page(request)", "StockTransfer"),
}

CSV_MANAGER_OLD = '''                    with transaction.atomic():
                        safe_stock, _ = BranchSafeStock.objects.get_or_create(
                            branch=branch, product=product
                        )
                        safe_stock.quantity += quantity
                        safe_stock.save()
                        StockMovement.objects.create(
                            branch=branch, product=product,
                            quantity=quantity, movement_type="IN",
                            performed_by=request.user,
                        )
                    count += 1
'''
CSV_MANAGER_NEW = '''                    # STOCK_APPROVALS_V1: held until the Director approves
                    from core.stock_approvals import submit_entry, batch_ref_for
                    submit_entry(
                        request.user, product, quantity, dest_tier="BRANCH", to_branch=branch,
                        source_type="MANUAL_OTHER", note="Bulk CSV upload", batch_ref=batch_ref_for(request),
                    )
                    count += 1
'''
CSV_MANAGER_MSG_OLD = 'msg = f"Imported {count} product(s) to branch safe."'
CSV_MANAGER_MSG_NEW = 'msg = f"Submitted {count} product(s) for Director approval. They join the branch safe once approved."'

CSV_RETAIL_OLD = '''                    with transaction.atomic():
                        stock, _ = StaffStock.objects.get_or_create(
                            staff=request.user, product=product
                        )
                        stock.quantity += quantity
                        stock.save()
                    count += 1
'''
CSV_RETAIL_NEW = '''                    # STOCK_APPROVALS_V1: held until the manager approves
                    from core.stock_approvals import submit_entry, batch_ref_for
                    submit_entry(
                        request.user, product, quantity, dest_tier="STAFF",
                        source_type=("MANUAL_DIRECTOR" if request.POST.get("received_from") == "DIRECTOR" else "MANUAL_OTHER"),
                        note="Bulk CSV upload", batch_ref=batch_ref_for(request),
                    )
                    count += 1
'''
CSV_RETAIL_MSG_OLD = 'msg = f"Uploaded {count} product(s) to your catalog."'
CSV_RETAIL_MSG_NEW = 'msg = f"Submitted {count} product(s) for approval. They count as your stock once your manager approves."'

SIDEBAR_BLOCK = '''
    {# STOCK_APPROVALS_V1 #}
    <div class="sidebar-section">
        <div class="sidebar-section-label">Stock Approvals</div>
        <a href="{% url 'stock_approvals' %}" class="sidebar-link">
            <span class="icon">&#9989;</span> Pending Approvals
            {% stock_approvals_count as sa_count %}{% if sa_count %}<span style="margin-left:auto;background:#ef4444;color:#fff;border-radius:999px;padding:0 .5rem;font-size:.7rem;font-weight:700;">{{ sa_count }}</span>{% endif %}
        </a>
        {% if user.role == "DIRECTOR" or user.role == "MANAGER" or user.is_superuser %}
        <a href="{% url 'stock_audit' %}" class="sidebar-link">
            <span class="icon">&#128269;</span> Stock Audit
        </a>
        {% endif %}
    </div>
    <div class="sidebar-divider"></div>
'''

RECEIVED_FROM_BLOCK = '''
        {# STOCK_APPROVALS_V1 #}
        <div class="form-group">
          <label>Stock received from *</label>
          <select name="received_from" required>
            <option value="OTHER">My branch manager / a supplier</option>
            <option value="DIRECTOR">The Director, directly to me</option>
          </select>
          <p style="font-size:.72rem;color:#6b7280;margin:.25rem 0 0;">Your manager must approve this before it counts as your stock.</p>
        </div>
'''

URL_BLOCK = '''
    # STOCK_APPROVALS_V1
    path('stock/approvals/', sav.stock_approvals, name='stock_approvals'),
    path('stock/approvals/<int:req_id>/approve/', sav.stock_approval_approve, name='stock_approval_approve'),
    path('stock/approvals/<int:req_id>/reject/', sav.stock_approval_reject, name='stock_approval_reject'),
    path('stock/approvals/<int:req_id>/cancel/', sav.stock_approval_cancel, name='stock_approval_cancel'),
    path('stock/approvals/<int:req_id>/edit/', sav.stock_approval_edit, name='stock_approval_edit'),
    path('stock/approvals/batch/<str:batch_ref>/', sav.stock_approval_batch, name='stock_approval_batch'),
    path('stock/audit/', sav.stock_audit, name='stock_audit'),
'''


def read(rel):
    with open(os.path.join(BASE_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def write_file(rel, content):
    path = os.path.join(BASE_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def backup(rel):
    path = os.path.join(BASE_DIR, rel)
    bak = path + ".pre_stockappr.bak"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)


def install_file(rel, content):
    path = os.path.join(BASE_DIR, rel)
    if os.path.exists(path):
        if MARKER in read(rel):
            print("SKIP  %s: already applied" % rel)
            return True
        backup(rel)
        write_file(rel, content)
        print("OK    %s: replaced (original kept as .pre_stockappr.bak)" % rel)
    else:
        write_file(rel, content)
        print("OK    %s: created" % rel)
    return True


def step_models():
    rel = "core/models.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    backup(rel)
    write_file(rel, src.rstrip("\n") + "\n" + MODELS_APPEND)
    print("OK    %s: added StockApprovalRequest and StockApprovalEvent" % rel)
    return True


def step_migration():
    mdir = os.path.join(BASE_DIR, "core", "migrations")
    names = sorted(f for f in os.listdir(mdir) if re.match(r"^\d{4}_.*\.py$", f))
    for name in names:
        with open(os.path.join(mdir, name), encoding="utf-8") as fh:
            if "StockApprovalRequest" in fh.read():
                print("SKIP  core/migrations/%s: stock approval migration already present" % name)
                return True
    if not names:
        print("FAIL  core/migrations: no existing migrations found; is this the project root?")
        return False
    last = names[-1]
    number = int(last[:4]) + 1
    new_name = "%04d_stock_approvals.py" % number
    content = MIGRATION_TEMPLATE.replace("__DEP__", last[:-3])
    write_file("core/migrations/" + new_name, content)
    print("OK    core/migrations/%s: created (depends on %s)" % (new_name, last[:-3]))
    return True


def _function_span(lines, name):
    starts = [i for i, l in enumerate(lines) if l.startswith("def %s(" % name)]
    if len(starts) != 1:
        return None
    i = starts[0]
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if line and not line[0].isspace() and not line.startswith(")"):
            break
        j += 1
    k = j
    while k > i + 1 and not lines[k - 1].strip():
        k -= 1
    return i, k


def patch_views():
    rel = "core/views.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    lines = src.split("\n")

    for name, (call, fingerprint) in FUNCTION_DELEGATES.items():
        span = _function_span(lines, name)
        if span is None:
            print("FAIL  %s: function %s not found exactly once; nothing edited." % (rel, name))
            return False
        i, k = span
        if fingerprint not in "\n".join(lines[i:k]):
            print("FAIL  %s: function %s looks different from what I expected; nothing edited." % (rel, name))
            return False
        body = [
            "    # STOCK_APPROVALS_V1: now goes through the approval workflow (core/stock_approval_views.py)",
            "    from core import stock_approval_views as _sav",
            "    return _sav.%s" % call,
        ]
        lines[i + 1:k] = body
    src = "\n".join(lines)

    for label, old, new in (
        ("upload_manager_csv stock block", CSV_MANAGER_OLD, CSV_MANAGER_NEW),
        ("upload_manager_csv message", CSV_MANAGER_MSG_OLD, CSV_MANAGER_MSG_NEW),
        ("upload_retail_csv stock block", CSV_RETAIL_OLD, CSV_RETAIL_NEW),
        ("upload_retail_csv message", CSV_RETAIL_MSG_OLD, CSV_RETAIL_MSG_NEW),
    ):
        if src.count(old) != 1:
            print("FAIL  %s: %s not found exactly once; nothing edited." % (rel, label))
            return False
        src = src.replace(old, new, 1)

    lines = src.split("\n")
    span = _function_span(lines, "upload_stock_csv")
    guard_old = 'if request.user.role not in ["DIRECTOR", "MANAGER"]:'
    if span is None or "\n".join(lines[span[0]:span[1]]).count(guard_old) != 1:
        print("FAIL  %s: upload_stock_csv role check not found; nothing edited." % rel)
        return False
    block = "\n".join(lines[span[0]:span[1]]).replace(
        guard_old, 'if request.user.role not in ["DIRECTOR"]:  # STOCK_APPROVALS_V1: managers can no longer overwrite branch stock')
    lines[span[0]:span[1]] = block.split("\n")

    backup(rel)
    write_file(rel, "\n".join(lines))
    print("OK    %s: stock actions now go through approvals; manager CSV overwrite closed" % rel)
    return True


def patch_urls():
    rel = "core/urls.py"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    anchor = "    path('release-stock/', views.release_stock, name='release_stock'),\n"
    imp = re.search(r"^from \. import views[ \t]*\n", src, flags=re.M)
    if src.count(anchor) != 1 or imp is None:
        print("FAIL  %s: expected anchors not found; nothing edited." % rel)
        return False
    backup(rel)
    src = src[:imp.end()] + "from . import stock_approval_views as sav  # STOCK_APPROVALS_V1\n" + src[imp.end():]
    src = src.replace(anchor, anchor + URL_BLOCK, 1)
    write_file(rel, src)
    print("OK    %s: approval and audit routes added" % rel)
    return True


def patch_base_html():
    rel = "templates/base.html"
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    if "{% load static %}" not in src:
        print("FAIL  %s: '{%% load static %%}' not found; nothing edited." % rel)
        return False
    nav = re.search(r'(<nav id="sidebar" class="sidebar">\s*\{% if user\.is_authenticated %\}[ \t]*\n)', src)
    if nav is None:
        print("FAIL  %s: sidebar anchor not found; nothing edited." % rel)
        return False
    backup(rel)
    src = src.replace("{% load static %}", "{% load static %}\n{% load stock_approval_tags %}{# STOCK_APPROVALS_V1 #}", 1)
    nav = re.search(r'(<nav id="sidebar" class="sidebar">\s*\{% if user\.is_authenticated %\}[ \t]*\n)', src)
    src = src[:nav.end()] + SIDEBAR_BLOCK + src[nav.end():]
    write_file(rel, src)
    print("OK    %s: Pending Approvals link (with badge) and Stock Audit link added" % rel)
    return True


def patch_retail_dashboard():
    rel = "templates/retail_dashboard.html"
    path = os.path.join(BASE_DIR, rel)
    if not os.path.exists(path):
        print("WARN  %s not found: staff will not see the 'received from' choice (default is manager-only approval)." % rel)
        return True
    src = read(rel)
    if MARKER in src:
        print("SKIP  %s: already applied" % rel)
        return True
    done = 0
    for url_name in ("staff_create_product", "upload_retail_csv"):
        pat = re.compile(r"(<form method=\"POST\" action=\"\{% url '" + url_name + r"' %\}\"[^>]*>\s*\{% csrf_token %\})")
        match = pat.search(src)
        if match:
            src = src[:match.end()] + RECEIVED_FROM_BLOCK + src[match.end():]
            done += 1
    if done == 0:
        print("WARN  %s: forms not found; staff will not see the 'received from' choice (default is manager-only approval)." % rel)
        return True
    backup(rel)
    write_file(rel, src)
    print("OK    %s: 'Stock received from' choice added to %d form(s)" % (rel, done))
    return True


def main():
    print("GPSL - stock approval workflow (Issue D)")
    print("-" * 58)
    ok = True
    ok = step_models() and ok
    ok = step_migration() and ok
    for rel, content in NEW_FILES.items():
        ok = install_file(rel, content) and ok
    ok = patch_views() and ok
    ok = patch_urls() and ok
    ok = patch_base_html() and ok
    ok = patch_retail_dashboard() and ok
    print("-" * 58)
    if not ok:
        print("Finished with a failure above. The file named in the FAIL line was NOT edited; send me this output.")
        sys.exit(1)
    print("Done. Next steps:")
    print("  1. python manage.py makemigrations --check     (should say: No changes detected)")
    print("  2. python manage.py migrate")
    print("  3. Restart the app. Open the sidebar > Pending Approvals and Stock Audit.")


if __name__ == "__main__":
    main()