# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_add_time_to_activity_expense'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyPerformanceArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(help_text='Always the 1st of the archived month')),
                ('retail_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('retail_quantity', models.IntegerField(default=0)),
                ('retail_gross_profit', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_revenue', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('multichoice_quantity', models.IntegerField(default=0)),
                ('total_expenses', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('net_profit', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('new_customers', models.IntegerField(default=0)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, help_text='Null = company-wide total row for this month', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='monthly_archives', to='core.branch')),
            ],
            options={
                'ordering': ['-month'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='monthlyperformancearchive',
            unique_together={('month', 'branch')},
        ),
    ]
