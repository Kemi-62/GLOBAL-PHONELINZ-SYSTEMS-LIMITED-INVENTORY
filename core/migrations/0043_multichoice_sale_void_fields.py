# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0042_staff_monthly_performance'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='multichoicesale',
            name='is_voided',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='void_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='voided_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='multichoicesale',
            name='voided_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='voided_mc_sales', to=settings.AUTH_USER_MODEL),
        ),
    ]
