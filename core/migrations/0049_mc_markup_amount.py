# MC_COMMISSION_V1
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0048_mc_sale_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="multichoicesale",
            name="markup_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
