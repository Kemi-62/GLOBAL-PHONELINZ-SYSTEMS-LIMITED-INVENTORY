# ROLES_V1
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0045_stock_approvals"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="branch_duties",
            field=models.BooleanField(default=False, help_text="Lets this person record expenses, send the daily WhatsApp report and enter device commission (normally manager chores)."),
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=[("SUPERADMIN", "Super Admin"), ("DIRECTOR", "Director"), ("MANAGER", "Manager"), ("TELECOM", "Telecom Staff"), ("RETAIL", "Phones & Accessories Staff"), ("MULTICHOICE", "MultiChoice Staff"), ("RETAIL_TELECOM", "Retail + Telecom Staff"), ("RETAIL_LEAD", "Retail + Manager-level Report"), ("SUB_DIRECTOR", "Sub Director")], max_length=20),
        ),
    ]
