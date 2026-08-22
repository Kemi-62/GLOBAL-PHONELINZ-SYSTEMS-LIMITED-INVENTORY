# Generated manually to match Django 5.0.2 migration style
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_add_online_sale_log'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MultiChoiceHardwareStock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_type', models.CharField(choices=[('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'), ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'), ('SINGLE_DECODER', 'Single Decoder'), ('REMOTE', 'Remote'), ('ADAPTER', 'Adapter'), ('ANTENNA', 'Antenna'), ('WIRE', 'Wire'), ('OTHER', 'Other')], max_length=20)),
                ('other_description', models.CharField(blank=True, default='', max_length=150)),
                ('quantity', models.IntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_stock', to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_stock', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='MultiChoiceHardwareSale',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_type', models.CharField(choices=[('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'), ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'), ('SINGLE_DECODER', 'Single Decoder'), ('REMOTE', 'Remote'), ('ADAPTER', 'Adapter'), ('ANTENNA', 'Antenna'), ('WIRE', 'Wire'), ('OTHER', 'Other')], max_length=20)),
                ('other_description', models.CharField(blank=True, default='', max_length=150)),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('iuc_number', models.CharField(blank=True, default='', max_length=30)),
                ('customer_name', models.CharField(blank=True, default='', max_length=150)),
                ('customer_phone', models.CharField(blank=True, default='', max_length=20)),
                ('notes', models.TextField(blank=True, default='')),
                ('date', models.DateField(auto_now_add=True)),
                ('time', models.TimeField(auto_now_add=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_sales', to='core.branch')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mc_hardware_sales', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='multichoicehardwarestock',
            unique_together={('staff', 'item_type', 'other_description')},
        ),
    ]
