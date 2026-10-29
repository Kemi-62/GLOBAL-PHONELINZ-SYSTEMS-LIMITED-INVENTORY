#!/usr/bin/env python3
"""
apply_roles_v1.py   (marker: ROLES_V1)

Adds three new roles WITHOUT changing the old ones:

  * Retail + Telecom Staff        one person, two departments (Retail | Telecom switcher)
  * Retail + Manager-level Report retail staff who also record expenses, send the daily
                                  WhatsApp report and enter device commission
  * Sub Director                  approves stock for the Director in every branch

Also adds:
  * a "Branch duties" switch (admin page) that gives any user those manager chores,
    for example one chosen staff member at Plaza
  * stock approvals for a branch with NO manager now come straight to the Director and
    Sub Director (and the Director's own release to such a branch no longer gets stuck)
  * Director page: Sub Director Activity (what was approved or rejected, by day range)
  * Director / Sub Director page: Branch Targets (set monthly telecom targets for any branch)

Run from the project root (the folder with manage.py):

    python apply_roles_v1.py
    python manage.py migrate

Safe to run twice. A second run prints SKIP lines and changes nothing.
All edits are checked BEFORE anything is written; if one cannot be placed the script
stops and changes nothing.
"""
import os, re, sys, shutil

MARK = "ROLES_V1"
ROOT = os.getcwd()

PATCHES = [('core/utils/decorators.py',
  '            if request.user.role not in roles:\n'
  '                return HttpResponseForbidden("You do not have permission to access this page.")',
  '            from core.roles import effective_roles  # ROLES_V1\n'
  '            if not (set(roles) & effective_roles(request.user)):\n'
  '                return HttpResponseForbidden("You do not have permission to access this page.")',
  'role_required understands the new roles'),
 ('core/models.py',
  "    ('MULTICHOICE', 'MultiChoice Staff'),\n    )\n",
  "    ('MULTICHOICE', 'MultiChoice Staff'),\n"
  "    ('RETAIL_TELECOM', 'Retail + Telecom Staff'),  # ROLES_V1\n"
  "    ('RETAIL_LEAD', 'Retail + Manager-level Report'),  # ROLES_V1\n"
  "    ('SUB_DIRECTOR', 'Sub Director'),  # ROLES_V1\n"
  '    )\n',
  'User.role choices'),
 ('core/models.py',
  '    is_locked = models.BooleanField(default=False)\n',
  '    is_locked = models.BooleanField(default=False)\n'
  "    branch_duties = models.BooleanField(default=False, help_text='Lets this person record expenses, send the daily WhatsApp report and "
  "enter device commission (normally manager chores).')  # ROLES_V1\n",
  'User.branch_duties'),
 ('core/admin.py',
  "            'fields': ('role', 'branch', 'failed_login_count', 'is_locked'),",
  "            'fields': ('role', 'branch', 'branch_duties', 'failed_login_count', 'is_locked'),",
  'admin shows branch duties switch'),
 ('core/stock_approvals.py',
  'STAFF_ROLES = ("RETAIL", "TELECOM", "MULTICHOICE")',
  'STAFF_ROLES = ("RETAIL", "TELECOM", "MULTICHOICE", "RETAIL_TELECOM", "RETAIL_LEAD")  # ROLES_V1',
  'approval engine: new staff roles can hold stock'),
 ('core/stock_approvals.py',
  'def is_director(user):\n'
  '    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", "") in ("DIRECTOR", "SUPERADMIN"))\n',
  'def is_director(user):\n'
  '    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", "") in ("DIRECTOR", "SUPERADMIN"))\n'
  '\n'
  '\n'
  '# ROLES_V1 -------------------------------------------------------------\n'
  '# The Sub Director approves and rejects like the Director. Set this to False to\n'
  "# keep the Director's own confirmation stage (manager entries, Director-safe\n"
  '# confirmations) for the Director alone.\n'
  'SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE = True\n'
  '\n'
  '\n'
  'def is_approver(user):\n'
  '    """Director level for APPROVING: the Director, or the Sub Director. Never used to start Director-safe moves."""\n'
  '    if is_director(user):\n'
  '        return True\n'
  '    return getattr(user, "role", "") == "SUB_DIRECTOR"\n'
  '\n'
  '\n'
  'def _managed_branch_ids():\n'
  '    """Branches that have at least one active manager."""\n'
  '    return set(m.User.objects.filter(role="MANAGER", is_active=True, branch__isnull=False)\n'
  '               .values_list("branch_id", flat=True))\n'
  '\n'
  '\n'
  'def _branch_has_manager(branch):\n'
  '    if branch is None:\n'
  '        return False\n'
  '    bid = getattr(branch, "id", branch)\n'
  '    return m.User.objects.filter(role="MANAGER", is_active=True, branch_id=bid).exists()\n'
  '\n'
  '\n'
  'def _notify_role_or_approvers(role, title, message, branch=None, notif_type="APPROVAL"):\n'
  '    """Tell the branch manager. If the branch has no manager, tell the Director and Sub Director instead."""\n'
  '    if role == "MANAGER" and branch is not None and not _branch_has_manager(branch):\n'
  '        for r in ("DIRECTOR", "SUB_DIRECTOR"):\n'
  '            _notify_role(r, title, "%s (%s has no manager)" % (message, branch.name), notif_type=notif_type)\n'
  '    else:\n'
  '        _notify_role(role, title, message, branch=branch, notif_type=notif_type)\n',
  'approval engine: is_approver and manager-less branch helpers'),
 ('core/stock_approvals.py',
  '    if req.approval_stage == "MANAGER":\n'
  '        _notify_role("MANAGER", headline, text, branch=req.to_branch)\n'
  '    elif req.approval_stage == "DIRECTOR":\n'
  '        _notify_role("DIRECTOR", headline, text)',
  '    if req.approval_stage == "MANAGER":\n'
  '        _notify_role_or_approvers("MANAGER", headline, text, branch=req.to_branch)\n'
  '    elif req.approval_stage == "DIRECTOR":\n'
  '        _notify_role("DIRECTOR", headline, text)\n'
  '        if SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE:\n'
  '            _notify_role("SUB_DIRECTOR", headline, text)',
  'approval engine: notifications reach the right approvers'),
 ('core/stock_approvals.py',
  '    director = is_director(user)\n    stage = req.approval_stage',
  '    director = is_approver(user)\n'
  '    if req.approval_stage == "DIRECTOR" and not is_director(user) and not SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE:\n'
  '        director = False\n'
  '    stage = req.approval_stage',
  'approval engine: Sub Director may approve'),
 ('core/stock_approvals.py',
  '    qs = m.StockApprovalRequest.objects.filter(status="PENDING").exclude(requested_by=user)\n'
  '    if is_director(user):\n'
  '        return qs.filter(approval_stage="DIRECTOR")',
  '    qs = m.StockApprovalRequest.objects.filter(status="PENDING").exclude(requested_by=user)\n'
  '    if is_approver(user):\n'
  '        from django.db.models import Q\n'
  '        director_stage = Q(approval_stage="DIRECTOR") if (is_director(user) or SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE) else Q(pk__in=[])\n'
  '        # ROLES_V1: requests for a branch with no manager come straight to the Director level\n'
  '        unmanaged = Q(approval_stage="MANAGER") & ~Q(to_branch_id__in=_managed_branch_ids())\n'
  '        return qs.filter(director_stage | unmanaged)',
  'approval engine: inbox includes manager-less branches'),
 ('core/stock_approvals.py',
  '    if not is_director(user):\n'
  '        return m.StockApprovalRequest.objects.none()\n'
  '    return m.StockApprovalRequest.objects.filter(status="PENDING").exclude(approval_stage="DIRECTOR")',
  '    if not is_approver(user):\n'
  '        return m.StockApprovalRequest.objects.none()\n'
  '    from django.db.models import Q\n'
  '    qs = m.StockApprovalRequest.objects.filter(status="PENDING").exclude(approval_stage="DIRECTOR")\n'
  '    # ROLES_V1: manager-less branches are in the actionable list already\n'
  '    return qs.exclude(Q(approval_stage="MANAGER") & ~Q(to_branch_id__in=_managed_branch_ids()))',
  'approval engine: oversight list has no duplicates'),
 ('core/stock_approvals.py',
  '    if dest_tier == "BRANCH":\n'
  '        return requester.role == "MANAGER" and to_branch is not None and requester.branch_id == to_branch.id',
  '    if dest_tier == "BRANCH":\n'
  '        if requester.role == "MANAGER" and to_branch is not None and requester.branch_id == to_branch.id:\n'
  '            return True\n'
  "        # ROLES_V1: a branch with no manager has nobody to accept, so the Director's own release completes at once\n"
  '        return bool(is_director(requester) and to_branch is not None and not _branch_has_manager(to_branch))',
  'approval engine: Director release to a manager-less branch no longer gets stuck'),
 ('core/stock_approvals.py',
  '    director = is_director(actor)\n    req.acted_on = True',
  '    director = is_approver(actor)\n'
  '    if req.approval_stage == "DIRECTOR" and not is_director(actor) and not SUB_DIRECTOR_ACTS_AT_DIRECTOR_STAGE:\n'
  '        director = False\n'
  '    req.acted_on = True',
  'approval engine: approve() treats Sub Director as approver'),
 ('core/stock_approvals.py',
  '        _notify_role("MANAGER", "Staff reduced their stock",',
  '        _notify_role_or_approvers("MANAGER", "Staff reduced their stock",',
  'approval engine: stock reductions reach approvers when no manager'),
 ('core/stock_approval_views.py',
  'from core.stock_approvals import StockError, is_director',
  'from core.stock_approvals import StockError, is_director, is_approver  # ROLES_V1\nfrom core.roles import has_role  # ROLES_V1',
  'approval views imports'),
 ('core/stock_approval_views.py',
  '    recent_q = base.exclude(status="PENDING")\n    if is_director(user):\n        pass',
  '    recent_q = base.exclude(status="PENDING")\n    if is_approver(user):\n        pass',
  'approval inbox: Sub Director sees all recent'),
 ('core/stock_approval_views.py',
  '        "is_director": is_director(user),\n        "can_audit": is_director(user) or user.role == "MANAGER",',
  '        "is_director": is_approver(user),\n        "can_audit": is_approver(user) or user.role == "MANAGER",',
  'approval inbox flags'),
 ('core/stock_approval_views.py',
  '    director = is_director(user)\n    if not director and not (user.role == "MANAGER" and user.branch_id):',
  '    director = is_approver(user)\n    if not director and not (user.role == "MANAGER" and user.branch_id):',
  'stock audit open to Sub Director'),
 ('core/stock_approval_views.py',
  '    if request.method == "POST" and request.user.role == "RETAIL":\n        try:\n            from core.models import RetailCategory',
  '    if request.method == "POST" and has_role(request.user, "RETAIL"):\n        try:\n            from core.models import RetailCategory',
  'add product open to new retail roles'),
 ('core/stock_approval_views.py',
  '            who = "your manager and then the Director" if req.source_type == "MANUAL_DIRECTOR" else "your manager"',
  '            _who = "your manager" if sa._branch_has_manager(request.user.branch) else "the Director\'s office"\n'
  '            who = (_who + " and then the Director") if req.source_type == "MANUAL_DIRECTOR" else _who',
  'approval wording for manager-less branches'),
 ('core/stock_approval_views.py',
  '    if request.user.role != "RETAIL":\n'
  '        return HttpResponseForbidden()\n'
  '    stock = get_object_or_404(m.StaffStock.objects.select_related("product"), id=stock_id, staff=request.user)',
  '    if not has_role(request.user, "RETAIL"):\n'
  '        return HttpResponseForbidden()\n'
  '    stock = get_object_or_404(m.StaffStock.objects.select_related("product"), id=stock_id, staff=request.user)',
  'adjust own stock open to new retail roles'),
 ('core/views.py',
  'from .utils.decorators import role_required',
  'from .utils.decorators import role_required\nfrom .roles import has_role, roles_for, STAFF_ROLES as ALL_STAFF_ROLES  # ROLES_V1',
  'views imports'),
 ('core/views.py',
  '        "TELECOM":     "staff_dashboard",\n    }\n    if getattr(user, "is_superuser", False):',
  '        "TELECOM":     "staff_dashboard",\n'
  '        "RETAIL_TELECOM": "retail_dashboard",  # ROLES_V1\n'
  '        "RETAIL_LEAD":    "retail_dashboard",  # ROLES_V1\n'
  '        "SUB_DIRECTOR":   "stock_approvals",  # ROLES_V1\n'
  '    }\n'
  '    if getattr(user, "is_superuser", False):',
  'dashboard url map'),
 ('core/views.py',
  '    "TELECOM":    "staff_dashboard",\n}\n\ndef _redirect_by_role(user):',
  '    "TELECOM":    "staff_dashboard",\n'
  '    "RETAIL_TELECOM": "retail_dashboard",  # ROLES_V1\n'
  '    "RETAIL_LEAD":    "retail_dashboard",  # ROLES_V1\n'
  '    "SUB_DIRECTOR":   "stock_approvals",  # ROLES_V1\n'
  '}\n'
  '\n'
  'def _redirect_by_role(user):',
  'login redirects'),
 ('core/views.py',
  '    if request.method == "POST" and request.user.role == "RETAIL":\n        StockRequest.objects.create(',
  '    if request.method == "POST" and has_role(request.user, "RETAIL"):\n        StockRequest.objects.create(',
  'request stock open to new retail roles'),
 ('core/views.py',
  'def edit_staff_stock_price(request, stock_id):\n    if request.user.role != "RETAIL":',
  'def edit_staff_stock_price(request, stock_id):\n    if not has_role(request.user, "RETAIL"):',
  'edit price open to new retail roles'),
 ('core/views.py',
  'def product_catalog(request):\n    if request.user.role != "RETAIL":',
  'def product_catalog(request):\n    if not has_role(request.user, "RETAIL"):',
  'catalog open to new retail roles'),
 ('core/views.py',
  '@role_required("MANAGER")\ndef record_expense(request):',
  '@role_required("MANAGER", "BRANCH_DUTIES")\ndef record_expense(request):',
  'expenses: branch duties may record'),
 ('core/views.py',
  '        messages.success(request, "Expense recorded.")\n    return redirect("manager_dashboard")',
  '        messages.success(request, "Expense recorded.")\n'
  '    return redirect("manager_dashboard" if request.user.role == "MANAGER" or request.user.is_superuser else "branch_duties")',
  'expenses: redirect for non-managers'),
 ('core/views.py',
  '@role_required("MANAGER")\ndef send_daily_report_whatsapp(request):',
  '@role_required("MANAGER", "BRANCH_DUTIES")\ndef send_daily_report_whatsapp(request):',
  'daily report: branch duties'),
 ('core/views.py',
  '@role_required("MANAGER")\ndef whatsapp_report_page(request):',
  '@role_required("MANAGER", "BRANCH_DUTIES")\ndef whatsapp_report_page(request):',
  'whatsapp report page: branch duties'),
 ('core/views.py',
  '@role_required("MANAGER")\ndef add_device_commission(request):',
  '@role_required("MANAGER", "BRANCH_DUTIES")\ndef add_device_commission(request):',
  'device commission: branch duties'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef director_all_branch_stock(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef director_all_branch_stock(request):',
  'all branch stock: Sub Director may view'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef all_branch_stock(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef all_branch_stock(request):',
  'all branch stock (second view): Sub Director may view'),
 ('core/views.py',
  '@role_required("DIRECTOR")\ndef stock_transfer_history(request):',
  '@role_required("DIRECTOR", "SUB_DIRECTOR")\ndef stock_transfer_history(request):',
  'transfer history: Sub Director may view'),
 ('core/views.py',
  '        "retail_staff": User.objects.filter(branch=request.user.branch, role="RETAIL"),',
  '        "retail_staff": User.objects.filter(branch=request.user.branch, role__in=roles_for("RETAIL")),',
  "today's sales staff list"),
 ('core/views.py',
  '    retail_staff = User.objects.filter(branch=branch, role="RETAIL")\n'
  '    telecom_staff = User.objects.filter(branch=branch, role="TELECOM")',
  '    retail_staff = User.objects.filter(branch=branch, role__in=roles_for("RETAIL"))\n'
  '    telecom_staff = User.objects.filter(branch=branch, role__in=roles_for("TELECOM"))',
  'manager dashboard staff lists'),
 ('core/views.py',
  'staff__branch=branch, staff__role="RETAIL", quantity__gt=0)',
  'staff__branch=branch, staff__role__in=roles_for("RETAIL"), quantity__gt=0)',
  'manager catalog: retail holders'),
 ('core/views.py',
  '            role__in=["RETAIL", "TELECOM", "MULTICHOICE"]\n        ).order_by("username"),',
  '            role__in=list(ALL_STAFF_ROLES)\n        ).order_by("username"),',
  'attendance staff filter'),
 ('core/views.py',
  '    all_staff = User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).select_related("branch").order_by("branch__name", "username")',
  '    all_staff = '
  'User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN","SUB_DIRECTOR"]).select_related("branch").order_by("branch__name", "username")',
  'attendance staff list excludes Sub Director'),
 ('core/views.py',
  '        "all_staff": User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN"]).order_by("username"),',
  '        "all_staff": User.objects.exclude(role__in=["DIRECTOR","SUPERADMIN","SUB_DIRECTOR"]).order_by("username"),',
  'commission staff list excludes Sub Director'),
 ('core/views.py',
  '    staff_list = UserModel.objects.filter(role="TELECOM").order_by("username")',
  '    staff_list = UserModel.objects.filter(role__in=roles_for("TELECOM")).order_by("username")',
  'router subscriptions staff list'),
 ('core/views.py',
  "        role__in=['RETAIL', 'TELECOM', 'MULTICHOICE', 'MANAGER']\n    ).order_by('username')",
  "        role__in=list(ALL_STAFF_ROLES) + ['MANAGER']\n    ).order_by('username')",
  'online sales staff list'),
 ('core/customer_history.py',
  '    if role in ROLE_DEPARTMENTS:\n        return [ROLE_DEPARTMENTS[role]], branch',
  '    if role == "RETAIL_TELECOM":  # ROLES_V1\n'
  '        return [DEPT_RETAIL, DEPT_TELECOM], branch\n'
  '    if role == "RETAIL_LEAD":  # ROLES_V1\n'
  '        return [DEPT_RETAIL], branch\n'
  '    if role in ROLE_DEPARTMENTS:\n'
  '        return [ROLE_DEPARTMENTS[role]], branch',
  'customer history scope'),
 ('core/signals.py',
  "        for director in User.objects.filter(role='DIRECTOR'):\n"
  '            Notification.objects.create(\n'
  '                recipient=director,\n'
  "                notif_type='STOCK_REQUEST',",
  "        for director in User.objects.filter(role__in=['DIRECTOR', 'SUB_DIRECTOR']):  # ROLES_V1\n"
  '            Notification.objects.create(\n'
  '                recipient=director,\n'
  "                notif_type='STOCK_REQUEST',",
  'stock request notices reach Sub Director'),
 ('core/management/commands/stock_alert_email.py',
  'staff__role="RETAIL"',
  'staff__role__in=["RETAIL", "RETAIL_TELECOM", "RETAIL_LEAD"]  # ROLES_V1',
  'stock alert email includes new retail roles'),
 ('core/management/commands/archive_staff_monthly_performance.py',
  '            role__in=["RETAIL", "TELECOM", "MULTICHOICE", "MANAGER"]',
  '            role__in=["RETAIL", "TELECOM", "MULTICHOICE", "MANAGER", "RETAIL_TELECOM", "RETAIL_LEAD"]  # ROLES_V1',
  'monthly staff archive includes new roles'),
 ('core/urls.py',
  'from . import customer_views  # CUSTOMER_HISTORY_V1',
  'from . import customer_views  # CUSTOMER_HISTORY_V1\nfrom . import roles_views as rv  # ROLES_V1',
  'urls import'),
 ('core/urls.py',
  "    path('director/momo-oversight/', views.momo_oversight, name='momo_oversight'),\n]",
  "    path('director/momo-oversight/', views.momo_oversight, name='momo_oversight'),\n"
  "    path('branch-duties/', rv.branch_duties, name='branch_duties'),  # ROLES_V1\n"
  "    path('targets/', rv.set_branch_targets, name='set_branch_targets'),  # ROLES_V1\n"
  "    path('director/sub-director-activity/', rv.sub_director_activity, name='sub_director_activity'),  # ROLES_V1\n"
  ']',
  'urls routes'),
 ('templates/base.html',
  '{% load stock_approval_tags %}{# STOCK_APPROVALS_V1 #}',
  '{% load stock_approval_tags %}{# STOCK_APPROVALS_V1 #}\n{% load role_tags %}{# ROLES_V1 #}',
  'base: load role tags'),
 ('templates/base.html',
  '<span class="topbar-role">{{ user.role }}</span>',
  '<span class="topbar-role" style="white-space:nowrap;">{{ user|role_badge }}</span>',
  'base: friendly role badge'),
 ('templates/base.html',
  '        {% if user.role == "DIRECTOR" or user.role == "MANAGER" or user.is_superuser %}\n'
  '        <a href="{% url \'stock_audit\' %}" class="sidebar-link">\n'
  '            <span class="icon">&#128269;</span> Stock Audit\n'
  '        </a>\n'
  '        {% endif %}',
  '        {% if user.role == "DIRECTOR" or user.role == "MANAGER" or user.role == "SUB_DIRECTOR" or user.is_superuser %}\n'
  '        <a href="{% url \'stock_audit\' %}" class="sidebar-link">\n'
  '            <span class="icon">&#128269;</span> Stock Audit\n'
  '        </a>\n'
  '        {% endif %}\n'
  '        {% if user.role == "DIRECTOR" or user.is_superuser %}{# ROLES_V1 #}\n'
  '        <a href="{% url \'sub_director_activity\' %}" class="sidebar-link">\n'
  '            <span class="icon">&#129489;&#8205;&#128188;</span> Sub Director Activity\n'
  '        </a>\n'
  '        <a href="{% url \'set_branch_targets\' %}" class="sidebar-link">\n'
  '            <span class="icon">&#127919;</span> Branch Targets\n'
  '        </a>\n'
  '        {% endif %}',
  'sidebar: audit for Sub Director, Director links'),
 ('templates/base.html',
  '    {% endif %}\n\n\n        <a href="{% url \'notifications_view\' %}" class="sidebar-link">',
  '    {% elif user.role == "RETAIL_TELECOM" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Retail</div>\n'
  '        <a href="{% url \'retail_dashboard\' %}" class="sidebar-link">\n'
  '            <span class="icon">🛍️</span> Retail Dashboard\n'
  '        </a>\n'
  '        <a href="{% url \'my_online_sales\' %}" class="sidebar-link">\n'
  '            <span class="icon">📱</span> Online Sales\n'
  '        </a>\n'
  '        <a href="{% url \'staff_create_product\' %}" class="sidebar-link">\n'
  '            <span class="icon">➕</span> Add Single Product\n'
  '        </a>\n'
  '        <a href="{% url \'upload_retail_csv\' %}" class="sidebar-link">\n'
  '            <span class="icon">📤</span> Bulk Upload Products\n'
  '        </a>\n'
  '        <a href="{% url \'request_stock\' %}" class="sidebar-link">\n'
  '            <span class="icon">📬</span> Request Stock\n'
  '        </a>\n'
  '    </div>\n'
  '    <div class="sidebar-divider"></div>\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Telecom</div>\n'
  '        <a href="{% url \'staff_dashboard\' %}" class="sidebar-link">\n'
  '            <span class="icon">📡</span> Telecom Dashboard\n'
  '        </a>\n'
  '        <a href="{% url \'router_subscriptions\' %}" class="sidebar-link">\n'
  '            <span class="icon">📡</span> Router Subscriptions\n'
  '        </a>\n'
  '        <a href="{% url \'record_physical_product\' %}" class="sidebar-link">\n'
  '            <span class="icon">📝</span> Record Activity\n'
  '        </a>\n'
  '        <a href="{% url \'staff_dashboard\' %}#devices" class="sidebar-link">\n'
  '            <span class="icon">📦</span> Device Stock & Sales\n'
  '        </a>\n'
  '    </div>\n'
  '    <div class="sidebar-divider"></div>\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Attendance</div>\n'
  '        <a href="{% url \'check_in\' %}" class="sidebar-link">\n'
  '            <span class="icon">🌅</span> Check In\n'
  '        </a>\n'
  '        <a href="{% url \'check_out\' %}" class="sidebar-link">\n'
  '            <span class="icon">🌆</span> Check Out\n'
  '        </a>\n'
  '        <a href="{% url \'attendance_history\' %}" class="sidebar-link">\n'
  '            <span class="icon">📅</span> My Attendance\n'
  '        </a>\n'
  '    </div>\n'
  '\n'
  '    {% elif user.role == "RETAIL_LEAD" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Retail</div>\n'
  '        <a href="{% url \'retail_dashboard\' %}" class="sidebar-link">\n'
  '            <span class="icon">🛍️</span> Retail Dashboard\n'
  '        </a>\n'
  '        <a href="{% url \'my_online_sales\' %}" class="sidebar-link">\n'
  '            <span class="icon">📱</span> Online Sales\n'
  '        </a>\n'
  '        <a href="{% url \'staff_create_product\' %}" class="sidebar-link">\n'
  '            <span class="icon">➕</span> Add Single Product\n'
  '        </a>\n'
  '        <a href="{% url \'upload_retail_csv\' %}" class="sidebar-link">\n'
  '            <span class="icon">📤</span> Bulk Upload Products\n'
  '        </a>\n'
  '        <a href="{% url \'request_stock\' %}" class="sidebar-link">\n'
  '            <span class="icon">📬</span> Request Stock\n'
  '        </a>\n'
  '    </div>\n'
  '    <div class="sidebar-divider"></div>\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Attendance</div>\n'
  '        <a href="{% url \'check_in\' %}" class="sidebar-link">\n'
  '            <span class="icon">🌅</span> Check In\n'
  '        </a>\n'
  '        <a href="{% url \'check_out\' %}" class="sidebar-link">\n'
  '            <span class="icon">🌆</span> Check Out\n'
  '        </a>\n'
  '        <a href="{% url \'attendance_history\' %}" class="sidebar-link">\n'
  '            <span class="icon">📅</span> My Attendance\n'
  '        </a>\n'
  '    </div>\n'
  '\n'
  '    {% elif user.role == "SUB_DIRECTOR" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Oversight</div>\n'
  '        <a href="{% url \'director_all_branch_stock\' %}" class="sidebar-link">\n'
  '            <span class="icon">📦</span> All Branch Stock\n'
  '        </a>\n'
  '        <a href="{% url \'stock_transfer_history\' %}" class="sidebar-link">\n'
  '            <span class="icon">🔄</span> Stock Transfer History\n'
  '        </a>\n'
  '        <a href="{% url \'set_branch_targets\' %}" class="sidebar-link">\n'
  '            <span class="icon">🎯</span> Branch Targets\n'
  '        </a>\n'
  '    </div>\n'
  '    {% endif %}\n'
  '\n'
  '    {% if user|has_role:"BRANCH_DUTIES" and user.role != "MANAGER" %}{# ROLES_V1 #}\n'
  '    <div class="sidebar-divider"></div>\n'
  '    <div class="sidebar-section">\n'
  '        <div class="sidebar-section-label">Branch Duties</div>\n'
  '        <a href="{% url \'branch_duties\' %}" class="sidebar-link">\n'
  '            <span class="icon">🧾</span> Branch Duties\n'
  '        </a>\n'
  '        <a href="{% url \'whatsapp_report_page\' %}" class="sidebar-link">\n'
  '            <span class="icon">📱</span> WhatsApp Report\n'
  '        </a>\n'
  '        <a href="{% url \'add_device_commission\' %}" class="sidebar-link">\n'
  '            <span class="icon">💰</span> Device Commission\n'
  '        </a>\n'
  '    </div>\n'
  '    {% endif %}\n'
  '\n'
  '\n'
  '        <a href="{% url \'notifications_view\' %}" class="sidebar-link">',
  'sidebar: menus for the three new roles'),
 ('templates/retail_dashboard.html',
  '{% block content %}',
  '{% block content %}\n{% include "partials/dept_switch.html" %}{# ROLES_V1 #}',
  'retail dashboard: department switcher'),
 ('templates/staff_dashboard.html',
  '{% block content %}',
  '{% block content %}\n{% include "partials/dept_switch.html" %}{# ROLES_V1 #}',
  'telecom dashboard: department switcher'),
 ('templates/device_commission_form.html',
  '<a href="{% url \'manager_dashboard\' %}" class="btn-sm btn-outline">← Dashboard</a>',
  '<a href="{% if user.role == \'MANAGER\' %}{% url \'manager_dashboard\' %}{% else %}{% url \'branch_duties\' %}{% endif %}" '
  'class="btn-sm btn-outline">← {% if user.role == \'MANAGER\' %}Dashboard{% else %}Branch Duties{% endif %}</a>',
  'device commission back link')]

NEWFILES = {'core/roles.py': '# ROLES_V1\n'
                  '"""Role lookup layer.\n'
                  '\n'
                  'The old roles (DIRECTOR, MANAGER, RETAIL, TELECOM, MULTICHOICE) are untouched.\n'
                  'Three newer roles are described here as combinations of abilities, so the rest\n'
                  'of the site can ask "may this person act as Retail?" instead of comparing names.\n'
                  '\n'
                  '    RETAIL_TELECOM  Retail + Telecom Staff        -> acts as RETAIL and TELECOM\n'
                  '    RETAIL_LEAD     Retail + Manager-level report -> acts as RETAIL, plus branch duties\n'
                  '                    (record expenses, daily WhatsApp report, device commission)\n'
                  '    SUB_DIRECTOR    approves stock for the Director, in every branch\n'
                  '\n'
                  'Any user (of any role) can also be given the "branch duties" switch in the\n'
                  'admin page, which adds BRANCH_DUTIES to what they can do.\n'
                  '"""\n'
                  '\n'
                  'RETAIL_TELECOM = "RETAIL_TELECOM"\n'
                  'RETAIL_LEAD = "RETAIL_LEAD"\n'
                  'SUB_DIRECTOR = "SUB_DIRECTOR"\n'
                  '\n'
                  'NEW_ROLE_CHOICES = (\n'
                  '    (RETAIL_TELECOM, "Retail + Telecom Staff"),\n'
                  '    (RETAIL_LEAD, "Retail + Manager-level Report"),\n'
                  '    (SUB_DIRECTOR, "Sub Director"),\n'
                  ')\n'
                  '\n'
                  '# what each role may act as, besides itself\n'
                  '_ALSO_ACTS_AS = {\n'
                  '    RETAIL_TELECOM: {"RETAIL", "TELECOM"},\n'
                  '    RETAIL_LEAD: {"RETAIL", "BRANCH_DUTIES"},\n'
                  '    SUB_DIRECTOR: set(),\n'
                  '}\n'
                  '\n'
                  '# every role that holds stock and sells (used for staff lists)\n'
                  'STAFF_ROLES = ("RETAIL", "TELECOM", "MULTICHOICE", RETAIL_TELECOM, RETAIL_LEAD)\n'
                  '\n'
                  '# roles that are Director-level people and not branch staff\n'
                  'DIRECTOR_LEVEL = ("DIRECTOR", "SUPERADMIN", SUB_DIRECTOR)\n'
                  '\n'
                  '\n'
                  'def effective_roles(user):\n'
                  '    """The set of role names this user may act as."""\n'
                  '    role = getattr(user, "role", "") or ""\n'
                  '    acts = {role} | _ALSO_ACTS_AS.get(role, set())\n'
                  '    if getattr(user, "branch_duties", False):\n'
                  '        acts.add("BRANCH_DUTIES")\n'
                  '    return acts\n'
                  '\n'
                  '\n'
                  'def has_role(user, *names):\n'
                  '    """True if the user may act as any of the named roles."""\n'
                  '    if not getattr(user, "is_authenticated", False):\n'
                  '        return False\n'
                  '    return bool(effective_roles(user) & set(names))\n'
                  '\n'
                  '\n'
                  'def roles_for(name):\n'
                  '    """Every stored role value that may act as `name` (for queries such as role__in=...)."""\n'
                  '    out = [name]\n'
                  '    for role, acts in _ALSO_ACTS_AS.items():\n'
                  '        if name in acts and role not in out:\n'
                  '            out.append(role)\n'
                  '    return out\n',
 'core/roles_views.py': '# ROLES_V1\n'
                        '"""Screens for the newer roles: Branch Duties, Sub Director targets, Sub Director activity."""\n'
                        'from datetime import date, timedelta\n'
                        '\n'
                        'from django.contrib import messages\n'
                        'from django.shortcuts import render, redirect\n'
                        'from django.utils import timezone\n'
                        '\n'
                        'from core import models as m\n'
                        'from core.utils.decorators import role_required\n'
                        '\n'
                        'SERVICE_TYPES = [\n'
                        '    ("SIM_REG", "SIM Registration"),\n'
                        '    ("SIM_SWAP", "SIM Swap"),\n'
                        '    ("SIM_UPGRADE", "SIM Upgrade"),\n'
                        '    ("DATA_ACTIVATION", "Data Activation"),\n'
                        '    ("RECHARGE", "Recharge"),\n'
                        ']\n'
                        '\n'
                        '\n'
                        '@role_required("BRANCH_DUTIES")\n'
                        'def branch_duties(request):\n'
                        '    """Small branch chores for people who are not a manager: expenses, daily report, device commission."""\n'
                        '    branch = request.user.branch\n'
                        '    expenses = []\n'
                        '    if branch:\n'
                        '        expenses = m.Expense.objects.filter(branch=branch).order_by("-date", "-time")[:10]\n'
                        '    return render(request, "branch_duties.html", {\n'
                        '        "branch": branch,\n'
                        '        "expenses": expenses,\n'
                        '        "categories": m.Expense.EXPENSE_CATEGORIES,\n'
                        '    })\n'
                        '\n'
                        '\n'
                        '@role_required("SUB_DIRECTOR", "DIRECTOR")\n'
                        'def set_branch_targets(request):\n'
                        '    """Monthly telecom targets for any branch (used where there is no manager to set them)."""\n'
                        '    first = date.today().replace(day=1)\n'
                        '    branches = m.Branch.objects.order_by("name")\n'
                        '    tags = m.DeviceTag.objects.select_related("branch").order_by("branch__name", "tag_name")\n'
                        '\n'
                        '    if request.method == "POST":\n'
                        '        branch = branches.filter(id=request.POST.get("branch") or 0).first()\n'
                        '        service = request.POST.get("service_type", "")\n'
                        '        tag = None\n'
                        '        raw_tag = request.POST.get("device_tag") or ""\n'
                        '        try:\n'
                        '            number = int(request.POST.get("target_number", ""))\n'
                        '        except (TypeError, ValueError):\n'
                        '            number = -1\n'
                        '        if branch is None:\n'
                        '            messages.error(request, "Please choose a branch.")\n'
                        '        elif service not in dict(SERVICE_TYPES):\n'
                        '            messages.error(request, "Please choose a service type.")\n'
                        '        elif number < 0:\n'
                        '            messages.error(request, "Please enter the target as a whole number.")\n'
                        '        else:\n'
                        '            if raw_tag:\n'
                        '                tag = tags.filter(id=raw_tag, branch=branch).first()\n'
                        '                if tag is None:\n'
                        '                    messages.error(request, "That device tag does not belong to the chosen branch.")\n'
                        '                    return redirect("set_branch_targets")\n'
                        '            m.ServiceTarget.objects.update_or_create(\n'
                        '                branch=branch, service_type=service, device_tag=tag, date=first,\n'
                        '                defaults={"target_number": number, "created_by": request.user},\n'
                        '            )\n'
                        '            messages.success(request, "Target set for %s." % branch.name)\n'
                        '        return redirect("set_branch_targets")\n'
                        '\n'
                        '    targets = m.ServiceTarget.objects.filter(date=first).select_related("branch", '
                        '"device_tag").order_by("branch__name", "service_type")\n'
                        '    return render(request, "subdirector_targets.html", {\n'
                        '        "branches": branches, "tags": tags, "targets": targets,\n'
                        '        "services": SERVICE_TYPES, "month": first,\n'
                        '    })\n'
                        '\n'
                        '\n'
                        '@role_required("DIRECTOR")\n'
                        'def sub_director_activity(request):\n'
                        '    """Director only: everything the Sub Director(s) approved or rejected recently."""\n'
                        '    try:\n'
                        '        days = int(request.GET.get("days", 7))\n'
                        '    except (TypeError, ValueError):\n'
                        '        days = 7\n'
                        '    if days not in (1, 7, 14, 30, 90):\n'
                        '        days = 7\n'
                        '    since = timezone.now() - timedelta(days=days)\n'
                        '    events = (m.StockApprovalEvent.objects\n'
                        '              .filter(actor__role="SUB_DIRECTOR", created_at__gte=since)\n'
                        '              .select_related("actor", "request", "request__product", "request__requested_by",\n'
                        '                              "request__to_branch", "request__from_branch")\n'
                        '              .order_by("-created_at"))\n'
                        '    rows = list(events[:500])\n'
                        '    summary = {}\n'
                        '    for e in rows:\n'
                        '        who = e.actor.username if e.actor else "(removed)"\n'
                        '        s = summary.setdefault(who, {"approved": 0, "rejected": 0, "other": 0})\n'
                        '        if "APPROVED" in e.action or e.action == "AUTO_COMPLETED":\n'
                        '            s["approved"] += 1\n'
                        '        elif e.action == "REJECTED":\n'
                        '            s["rejected"] += 1\n'
                        '        else:\n'
                        '            s["other"] += 1\n'
                        '    return render(request, "director/sub_director_activity.html", {\n'
                        '        "rows": rows, "summary": summary, "days": days,\n'
                        '        "has_sub_director": m.User.objects.filter(role="SUB_DIRECTOR").exists(),\n'
                        '    })\n',
 'core/templatetags/role_tags.py': '# ROLES_V1\n'
                                   'from django import template\n'
                                   '\n'
                                   'from core.roles import has_role as _has_role\n'
                                   '\n'
                                   'register = template.Library()\n'
                                   '\n'
                                   '\n'
                                   '@register.filter(name="has_role")\n'
                                   'def has_role_filter(user, names):\n'
                                   '    """{% if user|has_role:"RETAIL" %}  (comma separated names allowed)"""\n'
                                   '    return _has_role(user, *[n.strip() for n in str(names).split(",") if n.strip()])\n'
                                   '\n'
                                   '\n'
                                   '_BADGES = {\n'
                                   '    "RETAIL_TELECOM": "RETAIL + TELECOM",\n'
                                   '    "RETAIL_LEAD": "RETAIL LEAD",\n'
                                   '    "SUB_DIRECTOR": "SUB DIRECTOR",\n'
                                   '}\n'
                                   '\n'
                                   '\n'
                                   '@register.filter(name="role_badge")\n'
                                   'def role_badge(user):\n'
                                   '    """Short text for the role badge in the top bar."""\n'
                                   '    role = getattr(user, "role", "") or ""\n'
                                   '    return _BADGES.get(role, role)\n',
 'templates/branch_duties.html': '{% extends "base.html" %}\n'
                                 '{# ROLES_V1 #}\n'
                                 '{% block content %}\n'
                                 '<style>\n'
                                 '.bd-t{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 .3rem}\n'
                                 '.bd-s{font-size:.85rem;color:#6b7280;margin:0 0 1.2rem}\n'
                                 '.bd-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem;margin-bottom:1.2rem}\n'
                                 '.bd-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.1rem 1.2rem}\n'
                                 '.bd-card h3{font-size:.95rem;margin:0 0 .4rem;color:#111827}\n'
                                 '.bd-card p{font-size:.82rem;color:#6b7280;margin:0 0 .8rem}\n'
                                 '.bd-btn{display:inline-block;padding:.5rem '
                                 '1rem;border-radius:7px;background:#004F9F;color:#fff;text-decoration:none;font-weight:600;font-size:.85rem;border:none;cursor:pointer}\n'
                                 '.bd-btn.red{background:#ef4444}\n'
                                 '.bd-f label{display:block;font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:.6rem 0 .2rem}\n'
                                 '</style>\n'
                                 '\n'
                                 '<h1 class="bd-t">🧾 Branch Duties</h1>\n'
                                 '<p class="bd-s">{% if branch %}{{ branch.name }}{% else %}No branch set on your account{% endif %} '
                                 '&middot; small branch chores handled for the Director.</p>\n'
                                 '\n'
                                 '<div class="bd-grid">\n'
                                 '  <div class="bd-card">\n'
                                 '    <h3>📱 Daily WhatsApp Report</h3>\n'
                                 "    <p>Preview today's branch report and send it to the Director.</p>\n"
                                 '    <a href="{% url \'whatsapp_report_page\' %}" class="bd-btn">Open report</a>\n'
                                 '  </div>\n'
                                 '  <div class="bd-card">\n'
                                 '    <h3>💰 Device Commission</h3>\n'
                                 '    <p>Record the monthly SIM commission for device tags.</p>\n'
                                 '    <a href="{% url \'add_device_commission\' %}" class="bd-btn">Open commission form</a>\n'
                                 '  </div>\n'
                                 '</div>\n'
                                 '\n'
                                 '<div class="bd-grid">\n'
                                 '  <div class="bd-card">\n'
                                 '    <h3>➕ Record Expense</h3>\n'
                                 '    <form method="POST" action="{% url \'record_expense\' %}" class="bd-f">\n'
                                 '      {% csrf_token %}\n'
                                 '      <label>Category</label>\n'
                                 '      <select name="category" required>\n'
                                 '        {% for value, label in categories %}<option value="{{ value }}">{{ label }}</option>{% endfor '
                                 '%}\n'
                                 '      </select>\n'
                                 '      <label>Amount (₦)</label>\n'
                                 '      <input type="number" name="amount" step="0.01" min="0" required>\n'
                                 '      <label>Description</label>\n'
                                 '      <input type="text" name="description" placeholder="Brief description">\n'
                                 '      <button type="submit" class="bd-btn red" style="margin-top:.9rem;">Record Expense</button>\n'
                                 '    </form>\n'
                                 '  </div>\n'
                                 '  <div class="bd-card">\n'
                                 '    <h3>📋 Recent Expenses</h3>\n'
                                 '    <table>\n'
                                 '      <thead><tr><th>Category</th><th>Amount</th><th>Date</th></tr></thead>\n'
                                 '      <tbody>\n'
                                 '        {% for e in expenses %}\n'
                                 '        <tr><td>{{ e.get_category_display }}</td><td>₦{{ e.amount|floatformat:2 }}</td><td>{{ '
                                 'e.date|date:"d M Y" }}</td></tr>\n'
                                 '        {% empty %}\n'
                                 '        <tr><td colspan="3" style="text-align:center;color:#9ca3af;">No expenses recorded.</td></tr>\n'
                                 '        {% endfor %}\n'
                                 '      </tbody>\n'
                                 '    </table>\n'
                                 '  </div>\n'
                                 '</div>\n'
                                 '{% endblock %}\n',
 'templates/director/sub_director_activity.html': '{% extends "base.html" %}\n'
                                                  '{# ROLES_V1 #}\n'
                                                  '{% block content %}\n'
                                                  '<style>\n'
                                                  '.sd-t{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 .3rem}\n'
                                                  '.sd-s{font-size:.85rem;color:#6b7280;margin:0 0 1rem}\n'
                                                  '.sd-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.1rem '
                                                  '1.2rem;margin-bottom:1.2rem}\n'
                                                  '.sd-pill{display:inline-block;border-radius:999px;padding:.1rem '
                                                  '.6rem;font-size:.7rem;font-weight:700}\n'
                                                  '.sd-ok{background:#d1fae5;color:#065f46}.sd-no{background:#fee2e2;color:#991b1b}.sd-ot{background:#e5e7eb;color:#374151}\n'
                                                  '</style>\n'
                                                  '<div '
                                                  'style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.6rem;">\n'
                                                  '  <h1 class="sd-t">🧑\u200d💼 Sub Director Activity</h1>\n'
                                                  '  <form method="GET">\n'
                                                  '    <select name="days" onchange="this.form.submit()" style="width:auto;">\n'
                                                  '      <option value="1" {% if days == 1 %}selected{% endif %}>Last 24 hours</option>\n'
                                                  '      <option value="7" {% if days == 7 %}selected{% endif %}>Last 7 days</option>\n'
                                                  '      <option value="14" {% if days == 14 %}selected{% endif %}>Last 14 days</option>\n'
                                                  '      <option value="30" {% if days == 30 %}selected{% endif %}>Last 30 days</option>\n'
                                                  '      <option value="90" {% if days == 90 %}selected{% endif %}>Last 90 days</option>\n'
                                                  '    </select>\n'
                                                  '  </form>\n'
                                                  '</div>\n'
                                                  '<p class="sd-s">Every stock request your Sub Director approved or rejected. Open Stock '
                                                  'Audit for the full trail of any request.</p>\n'
                                                  '\n'
                                                  '{% if not has_sub_director %}\n'
                                                  '<div class="sd-card" style="color:#6b7280;">No Sub Director account exists yet. Create '
                                                  'one in the admin page and set its role to Sub Director.</div>\n'
                                                  '{% else %}\n'
                                                  '<div class="sd-card">\n'
                                                  '  <p style="font-weight:700;margin:0 0 .6rem;">Summary</p>\n'
                                                  '  <table>\n'
                                                  '    <thead><tr><th>Sub '
                                                  'Director</th><th>Approved</th><th>Rejected</th><th>Other</th></tr></thead>\n'
                                                  '    <tbody>\n'
                                                  '      {% for who, s in summary.items %}\n'
                                                  '      <tr><td>{{ who }}</td><td>{{ s.approved }}</td><td>{{ s.rejected }}</td><td>{{ '
                                                  's.other }}</td></tr>\n'
                                                  '      {% empty %}\n'
                                                  '      <tr><td colspan="4" style="text-align:center;color:#9ca3af;">No activity in this '
                                                  'period.</td></tr>\n'
                                                  '      {% endfor %}\n'
                                                  '    </tbody>\n'
                                                  '  </table>\n'
                                                  '</div>\n'
                                                  '<div class="sd-card">\n'
                                                  '  <p style="font-weight:700;margin:0 0 .6rem;">Activity list</p>\n'
                                                  '  <table>\n'
                                                  '    '
                                                  '<thead><tr><th>When</th><th>Who</th><th>Action</th><th>Item</th><th>Qty</th><th>Branch</th><th>Requested '
                                                  'by</th><th>Note</th></tr></thead>\n'
                                                  '    <tbody>\n'
                                                  '      {% for e in rows %}\n'
                                                  '      <tr>\n'
                                                  '        <td>{{ e.created_at|date:"d M H:i" }}</td>\n'
                                                  '        <td>{{ e.actor.username|default:"—" }}</td>\n'
                                                  '        <td>{% if e.action == "REJECTED" %}<span class="sd-pill '
                                                  'sd-no">Rejected</span>{% elif "APPROVED" in e.action or e.action == "AUTO_COMPLETED" '
                                                  '%}<span class="sd-pill sd-ok">Approved</span>{% else %}<span class="sd-pill sd-ot">{{ '
                                                  'e.action|title }}</span>{% endif %}</td>\n'
                                                  '        <td>{{ e.request.product.model_name }}</td>\n'
                                                  '        <td>{{ e.request.quantity }}</td>\n'
                                                  '        <td>{% if e.request.to_branch %}{{ e.request.to_branch.name }}{% elif '
                                                  'e.request.from_branch %}{{ e.request.from_branch.name }}{% else %}—{% endif %}</td>\n'
                                                  '        <td>{{ e.request.requested_by.username|default:"—" }}</td>\n'
                                                  '        <td>{{ e.detail|truncatechars:70 }}</td>\n'
                                                  '      </tr>\n'
                                                  '      {% empty %}\n'
                                                  '      <tr><td colspan="8" style="text-align:center;color:#9ca3af;">Nothing in this '
                                                  'period.</td></tr>\n'
                                                  '      {% endfor %}\n'
                                                  '    </tbody>\n'
                                                  '  </table>\n'
                                                  '</div>\n'
                                                  '{% endif %}\n'
                                                  '{% endblock %}\n',
 'templates/partials/dept_switch.html': '{% load role_tags %}{# ROLES_V1 #}\n'
                                        '{% if user.role == "RETAIL_TELECOM" or user|has_role:"BRANCH_DUTIES" %}\n'
                                        '<div style="display:flex;gap:.4rem;flex-wrap:wrap;margin:0 0 1rem;">\n'
                                        '  {% if user.role == "RETAIL_TELECOM" %}\n'
                                        '  <a href="{% url \'retail_dashboard\' %}" style="padding:.45rem '
                                        '1rem;border-radius:999px;font-size:.82rem;font-weight:700;text-decoration:none;{% if request.path '
                                        "== '/retail/' %}background:#004F9F;color:#fff;{% else %}background:#e5e7eb;color:#374151;{% endif "
                                        '%}">🛍️ Retail</a>\n'
                                        '  <a href="{% url \'staff_dashboard\' %}" style="padding:.45rem '
                                        '1rem;border-radius:999px;font-size:.82rem;font-weight:700;text-decoration:none;{% if request.path '
                                        "== '/staff/' or request.path == '/telecom/' %}background:#004F9F;color:#fff;{% else "
                                        '%}background:#e5e7eb;color:#374151;{% endif %}">📡 Telecom</a>\n'
                                        '  {% endif %}\n'
                                        '  {% if user|has_role:"BRANCH_DUTIES" and user.role != "MANAGER" %}\n'
                                        '  <a href="{% url \'branch_duties\' %}" style="padding:.45rem '
                                        '1rem;border-radius:999px;font-size:.82rem;font-weight:700;text-decoration:none;background:#fef3c7;color:#92400e;">🧾 '
                                        'Branch Duties</a>\n'
                                        '  {% endif %}\n'
                                        '</div>\n'
                                        '{% endif %}\n',
 'templates/subdirector_targets.html': '{% extends "base.html" %}\n'
                                       '{# ROLES_V1 #}\n'
                                       '{% block content %}\n'
                                       '<style>\n'
                                       '.st-t{font-size:1.3rem;font-weight:700;color:#004F9F;margin:0 0 .3rem}\n'
                                       '.st-s{font-size:.85rem;color:#6b7280;margin:0 0 1.2rem}\n'
                                       '.st-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:1.1rem '
                                       '1.2rem;margin-bottom:1.2rem}\n'
                                       '.st-f{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.8rem;align-items:end}\n'
                                       '.st-f label{display:block;font-size:.72rem;text-transform:uppercase;color:#6b7280;margin:0 0 '
                                       '.2rem}\n'
                                       '.st-btn{padding:.55rem '
                                       '1.1rem;border-radius:7px;background:#004F9F;color:#fff;font-weight:600;font-size:.85rem;border:none;cursor:pointer}\n'
                                       '</style>\n'
                                       '<h1 class="st-t">🎯 Branch Targets</h1>\n'
                                       '<p class="st-s">Set the monthly telecom target for any branch, including branches without a '
                                       'manager. Month: {{ month|date:"F Y" }}.</p>\n'
                                       '\n'
                                       '<div class="st-card">\n'
                                       '  <form method="POST" class="st-f">\n'
                                       '    {% csrf_token %}\n'
                                       '    <div><label>Branch</label>\n'
                                       '      <select name="branch" required>\n'
                                       '        <option value="">Choose…</option>\n'
                                       '        {% for b in branches %}<option value="{{ b.id }}">{{ b.name }}</option>{% endfor %}\n'
                                       '      </select></div>\n'
                                       '    <div><label>Service</label>\n'
                                       '      <select name="service_type" required>\n'
                                       '        {% for value, label in services %}<option value="{{ value }}">{{ label }}</option>{% '
                                       'endfor %}\n'
                                       '      </select></div>\n'
                                       '    <div><label>Device tag (optional)</label>\n'
                                       '      <select name="device_tag">\n'
                                       '        <option value="">All / Generic</option>\n'
                                       '        {% for t in tags %}<option value="{{ t.id }}">{{ t.tag_name }} ({{ t.branch.name '
                                       '}})</option>{% endfor %}\n'
                                       '      </select></div>\n'
                                       '    <div><label>Target</label><input type="number" name="target_number" min="0" required></div>\n'
                                       '    <div><button type="submit" class="st-btn">Set target</button></div>\n'
                                       '  </form>\n'
                                       '</div>\n'
                                       '\n'
                                       '<div class="st-card">\n'
                                       '  <p style="font-weight:700;margin:0 0 .6rem;">Targets for {{ month|date:"F Y" }}</p>\n'
                                       '  <table>\n'
                                       '    '
                                       '<thead><tr><th>Branch</th><th>Service</th><th>Tag</th><th>Target</th><th>Done</th><th>%</th></tr></thead>\n'
                                       '    <tbody>\n'
                                       '      {% for t in targets %}\n'
                                       '      <tr><td>{{ t.branch.name }}</td><td>{{ t.get_service_type_display|default:t.service_type '
                                       '}}</td><td>{{ t.device_tag.tag_name|default:"—" }}</td><td>{{ t.target_number }}</td><td>{{ '
                                       't.achieved }}</td><td>{{ t.percentage }}%</td></tr>\n'
                                       '      {% empty %}\n'
                                       '      <tr><td colspan="6" style="text-align:center;color:#9ca3af;">No targets set this '
                                       'month.</td></tr>\n'
                                       '      {% endfor %}\n'
                                       '    </tbody>\n'
                                       '  </table>\n'
                                       '</div>\n'
                                       '{% endblock %}\n'}

MIGRATION = '# ROLES_V1\nfrom django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n\n    dependencies = [\n        ("core", "@@LAST@@"),\n    ]\n\n    operations = [\n        migrations.AddField(\n            model_name="user",\n            name="branch_duties",\n            field=models.BooleanField(default=False, help_text="Lets this person record expenses, send the daily WhatsApp report and enter device commission (normally manager chores)."),\n        ),\n        migrations.AlterField(\n            model_name="user",\n            name="role",\n            field=models.CharField(choices=[("SUPERADMIN", "Super Admin"), ("DIRECTOR", "Director"), ("MANAGER", "Manager"), ("TELECOM", "Telecom Staff"), ("RETAIL", "Phones & Accessories Staff"), ("MULTICHOICE", "MultiChoice Staff"), ("RETAIL_TELECOM", "Retail + Telecom Staff"), ("RETAIL_LEAD", "Retail + Manager-level Report"), ("SUB_DIRECTOR", "Sub Director")], max_length=20),\n        ),\n    ]\n'

def p(rel): return os.path.join(ROOT, *rel.split("/"))
def read(rel):
    with open(p(rel), encoding="utf-8") as f: return f.read()

if not os.path.exists(p("manage.py")) or not os.path.isdir(p("core")):
    print("ABORT: run this from the folder that contains manage.py"); sys.exit(1)

# ---------- phase 1: work everything out in memory ----------
texts, errors, plan = {}, [], []
for rel, old, new, label in PATCHES:
    if not os.path.exists(p(rel)):
        errors.append("missing file: " + rel); continue
    t = texts.get(rel)
    if t is None: t = read(rel)
    if new in t:
        plan.append(("SKIP", label)); texts[rel] = t; continue
    n = t.count(old)
    if n != 1:
        errors.append("%s: expected exactly 1 match for [%s], found %d" % (rel, label, n)); texts[rel] = t; continue
    texts[rel] = t.replace(old, new, 1)
    plan.append(("OK", label))
if errors:
    print("ABORT: nothing was changed.\n")
    for e in errors: print("  -", e)
    sys.exit(1)

newfiles = []
for rel, content in NEWFILES.items():
    if os.path.exists(p(rel)):
        if read(rel) == content: plan.append(("SKIP", "file " + rel))
        else:
            newfiles.append((rel, content, True)); plan.append(("OK", "file " + rel + " (updated)"))
    else:
        newfiles.append((rel, content, False)); plan.append(("OK", "file " + rel))

# migration
mig_dir = p("core/migrations")
nums = sorted(f for f in os.listdir(mig_dir) if re.match(r"^\d{4}_.*\.py$", f))
have_mig = any(MARK in open(os.path.join(mig_dir, f), encoding="utf-8").read() for f in nums)
mig_name = None
if have_mig:
    plan.append(("SKIP", "migration"))
else:
    last = nums[-1][:-3]
    mig_name = "%04d_roles_v1.py" % (int(last[:4]) + 1)
    plan.append(("OK", "migration " + mig_name))

# ---------- phase 2: write ----------
def backup(rel):
    b = p(rel) + ".pre_roles.bak"
    if not os.path.exists(b): shutil.copy2(p(rel), b)
changed = [r for r, t in texts.items() if t != read(r)]
for rel in changed:
    backup(rel)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(texts[rel])
for rel, content, existed in newfiles:
    os.makedirs(os.path.dirname(p(rel)), exist_ok=True)
    if existed: backup(rel)
    with open(p(rel), "w", encoding="utf-8", newline="") as f: f.write(content)
if mig_name:
    with open(os.path.join(mig_dir, mig_name), "w", encoding="utf-8", newline="") as f:
        f.write(MIGRATION.replace("@@LAST@@", last))

for status, label in plan:
    print(("OK   " if status == "OK" else "SKIP ") + label)
print()
if changed or newfiles or mig_name:
    print("Done. Next:  python manage.py migrate   then commit, push and redeploy.")
else:
    print("Nothing to do: already applied.")