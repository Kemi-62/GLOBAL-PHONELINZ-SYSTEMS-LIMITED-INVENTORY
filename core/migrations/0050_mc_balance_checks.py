# MC_COMMISSION_V2
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0049_mc_markup_amount"),
    ]

    operations = [
        migrations.CreateModel(
            name="MultiChoiceBalanceCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("checked_at", models.DateTimeField(auto_now_add=True)),
                ("expected_balance", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("actual_balance", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("difference", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[("BASELINE", "First balance (starting point)"), ("MATCHED", "Matched"), ("COMMISSION", "Commission detected (waiting)"), ("COMMISSION_OK", "Commission confirmed"), ("REJECTED", "Commission rejected"), ("SHORTAGE", "Shortage (to review)"), ("SHORTAGE_REVIEWED", "Shortage reviewed"), ("SKIPPED", "Skipped")], default="MATCHED", max_length=20)),
                ("screenshot", models.ImageField(blank=True, null=True, upload_to="mc_balance_proofs/")),
                ("note", models.TextField(blank=True, default="")),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="core.branch")),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="mc_balance_decisions", to=settings.AUTH_USER_MODEL)),
                ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mc_balance_checks", to=settings.AUTH_USER_MODEL)),
                ("weekly_report", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="balance_checks", to="core.multichoiceweeklyreport")),
            ],
            options={"ordering": ["-checked_at"]},
        ),
    ]
