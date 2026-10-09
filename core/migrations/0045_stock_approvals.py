# STOCK_APPROVALS_V1 - generated with Django 5.0.x makemigrations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0044_daily_momo_balance"),
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
