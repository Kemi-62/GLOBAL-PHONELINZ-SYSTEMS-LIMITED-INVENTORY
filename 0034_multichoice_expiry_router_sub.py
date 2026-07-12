# Generated migration 0034 - MultiChoice expiry + RouterSubscription
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_catalogcategory_slideshowitem_catalogproduct'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add expiry_date to MultiChoiceSale
        migrations.AddField(
            model_name='multichoicesale',
            name='expiry_date',
            field=models.DateField(
                null=True, blank=True,
                help_text='Auto-set to subscription date + 30 days'
            ),
        ),

        # New RouterSubscription model
        migrations.CreateModel(
            name='RouterSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_name', models.CharField(max_length=150)),
                ('customer_phone', models.CharField(max_length=20)),
                ('alt_phone', models.CharField(max_length=20, blank=True, default='')),
                ('router_number', models.CharField(max_length=100, help_text='Router serial / SIM number')),
                ('router_type', models.CharField(
                    max_length=20,
                    choices=[('4G', '4G Router'), ('5G', '5G Router')],
                    default='4G',
                )),
                ('network', models.CharField(max_length=50, blank=True, default='MTN')),
                ('subscription_date', models.DateField(default=django.utils.timezone.now)),
                ('expiry_date', models.DateField(help_text='Auto-set to subscription_date + 30 days')),
                ('month_number', models.PositiveIntegerField(default=1, help_text='Which subscription month (1 or 2)')),
                ('amount', models.DecimalField(max_digits=12, decimal_places=2, default=0)),
                ('is_active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('staff', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.CASCADE, related_name='router_subs')),
                ('branch', models.ForeignKey('core.Branch', on_delete=django.db.models.deletion.CASCADE, related_name='router_subs')),
            ],
            options={
                'verbose_name': 'Router Subscription',
                'verbose_name_plural': 'Router Subscriptions',
                'ordering': ['expiry_date'],
            },
        ),
    ]
