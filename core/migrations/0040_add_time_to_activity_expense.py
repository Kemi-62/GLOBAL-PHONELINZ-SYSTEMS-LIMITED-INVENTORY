# Generated manually to match Django 5.0.2 migration style
import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0039_multichoice_hardware'),
    ]

    operations = [
        migrations.AddField(
            model_name='serviceactivity',
            name='time',
            field=models.TimeField(auto_now_add=True, default=datetime.time(12, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='expense',
            name='time',
            field=models.TimeField(auto_now_add=True, default=datetime.time(12, 0)),
            preserve_default=False,
        ),
    ]
