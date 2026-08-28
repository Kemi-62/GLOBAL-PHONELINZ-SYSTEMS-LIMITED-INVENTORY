# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_monthly_performance_archive'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffMonthlyPerformanceArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(help_text='Always the 1st of the archived month')),
                ('retail_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('retail_quantity', models.IntegerField(default=0)),
                ('multichoice_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_quantity', models.IntegerField(default=0)),
                ('hardware_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('hardware_quantity', models.IntegerField(default=0)),
                ('online_sales_count', models.IntegerField(default=0)),
                ('online_sales_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('telecom_activity_count', models.IntegerField(default=0)),
                ('days_present', models.IntegerField(default=0)),
                ('days_late', models.IntegerField(default=0)),
                ('days_absent', models.IntegerField(default=0)),
                ('email_sent', models.BooleanField(default=False)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_archives', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-month'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='staffmonthlyperformancearchive',
            unique_together={('staff', 'month')},
        ),
    ]
