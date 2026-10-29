# MC_RENEWALS_V2
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0046_roles_v1"),
    ]

    operations = [
        migrations.AddField(
            model_name="multichoicesale",
            name="months_paid",
            field=models.PositiveSmallIntegerField(default=1, help_text="How many months this payment covers (used for renewal reminders)."),
        ),
    ]
