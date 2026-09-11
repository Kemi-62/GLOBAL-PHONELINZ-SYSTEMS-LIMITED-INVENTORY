# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_multichoice_sale_void_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyMomoBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('opening_balance', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('additional_funds', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('closing_balance', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('is_closed', models.BooleanField(default=False)),
                ('recorded_at', models.DateTimeField(blank=True, null=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='momo_balances', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='dailymomobalance',
            unique_together={('staff', 'date')},
        ),
    ]
