# MC_PRICING_V1
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_mc_months_paid"),
    ]

    operations = [
        migrations.AddField(
            model_name="multichoicesale",
            name="sale_category",
            field=models.CharField(choices=[("CUSTOMER", "Customer subscription"), ("ACTIVATION", "Activation"), ("OFFICE", "Office subscription"), ("DIRECTOR", "Given by Director")], default="CUSTOMER", max_length=12),
        ),
    ]
