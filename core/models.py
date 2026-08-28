from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum
from django.conf import settings
from datetime import date
from django.utils import timezone
from decimal import Decimal
import json

# -----------------------
# Branch
# -----------------------
class Branch(models.Model):
    name = models.CharField(max_length=100)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    allowed_radius = models.IntegerField(default=300)
    location_locked = models.BooleanField(default=False)

    def __str__(self):
        return str(self.name)

    @property
    def full_address(self):
        parts = [p for p in [self.street_address, self.city, self.state] if p]
        return ", ".join(parts) if parts else "Address not set"


# -----------------------
# Custom User
# -----------------------
class User(AbstractUser):
    ROLE_CHOICES = (
    ('SUPERADMIN', 'Super Admin'),
    ('DIRECTOR', 'Director'),
    ('MANAGER', 'Manager'),
    ('TELECOM', 'Telecom Staff'),
    ('RETAIL', 'Phones & Accessories Staff'),
    ('MULTICHOICE', 'MultiChoice Staff'),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    failed_login_count = models.IntegerField(default=0)
    is_locked = models.BooleanField(default=False)

    def __str__(self):
        return str(self.username)


# -----------------------
# Device Tags (SIM Registration Only)
# -----------------------
class DeviceTag(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    tag_name = models.CharField(max_length=100)

    def __str__(self):
        return str(self.tag_name)


# -----------------------
# Daily Service Targets
# -----------------------
class ServiceTarget(models.Model):
    SERVICE_CHOICES = [
        ('SIM_REG', 'SIM Registration'),
        ('SIM_SWAP', 'SIM Swap'),
        ('SIM_UPGRADE', 'SIM Upgrade'),
        ('GOTV', 'GOTV Subscription'),
        ('DSTV', 'DSTV Subscription'),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=50, choices=SERVICE_CHOICES)
    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE, null=True, blank=True)
    target_number = models.PositiveIntegerField()
    date = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        unique_together = ('branch', 'service_type', 'device_tag', 'date')

    def achieved(self):
        total = ServiceActivity.objects.filter(
            branch=self.branch,
            service_type=self.service_type,
            date=self.date
        ).aggregate(Sum('quantity'))['quantity__sum']
        return total or 0

    def percentage(self):
        if self.target_number == 0:
            return 0
        return round((self.achieved() / self.target_number) * 100, 2)

    def remaining(self):
        return max(self.target_number - self.achieved(), 0)

    def __str__(self):
        return f"{self.branch} - {self.service_type} - {self.date}"


# -----------------------
# Service Activity (Daily Work Entry)
# -----------------------
class DirectorSafeStock(models.Model):
    product = models.ForeignKey('Product', on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    date_added = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    @property
    def total_value(self):
        if self.product:
            return self.quantity * self.product.cost_price
        return 0

    def __str__(self):
        if self.product:
            return f"Director Safe - {self.product.model_name}: {self.quantity}"
        return f"Director Safe - {self.quantity} units"

    class Meta:
        verbose_name_plural = "Director Safe Stock"


class ServiceActivity(models.Model):
    SERVICE_CHOICES = (
        ('SIM_REG', 'SIM Registration'),
        ('SIM_SWAP', 'SIM Swap'),
        ('SIM_RET', 'SIM Retrieval'),
        ('NIN_LINK', 'NIN Linking'),
        ('MIFI', 'MiFi Sale'),
        ('ROUTER', 'Router Sale'),
        ('WHOLESALE_SIM', 'Wholesale SIM'),
    )

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=50)
    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    approved = models.BooleanField(default=False)
    customer_phone = models.CharField(max_length=20, blank=True, default='')
    customer_name  = models.CharField(max_length=200, blank=True, default='')
    price          = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    requires_approval = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.service_type != 'SIM_REG':
            self.device_tag = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_type} - {self.quantity}"


class Performance(models.Model):
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=100)
    number_achieved = models.IntegerField()
    date = models.DateField()

    def __str__(self):
        return f"{self.staff.username} - {self.service_type}"

class RetailCategory(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class RetailSubCategory(models.Model):
    category = models.ForeignKey(RetailCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.category.name} - {self.name}"


class RetailSubSubCategory(models.Model):
    subcategory = models.ForeignKey(RetailSubCategory, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.subcategory} - {self.name}"



class Expense(models.Model):
    EXPENSE_CATEGORIES = (
        ('RENT', 'Rent'),
        ('ELECTRICITY', 'Electricity'),
        ('TRANSPORT', 'Transport'),
        ('STATIONERY', 'Stationery'),
        ('REPAIRS', 'Repairs'),
        ('OTHER', 'Other'),
    )
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    category = models.CharField(max_length=20, choices=EXPENSE_CATEGORIES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.category} - {self.amount} at {self.branch.name}"


class Product(models.Model):
    subsubcategory = models.ForeignKey(RetailSubSubCategory, on_delete=models.CASCADE, null=True, blank=True)
    subcategory = models.ForeignKey(RetailSubCategory, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200, null=True, blank=True)
    model_name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    imei_serial = models.CharField(max_length=100, unique=True, null=True, blank=True)

    color = models.CharField(max_length=50, blank=True, null=True, help_text="Product color variant")
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name or self.model_name} ({self.model_name}) - {self.imei_serial or 'No IMEI'}"


class BranchSafeStock(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.branch.name} - {self.product.model_name}"


class StaffStock(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.staff.username} - {self.product.model_name}"


class StockMovement(models.Model):
    MOVEMENT_TYPE = (
        ('IN', 'Stock Entry'),
        ('OUT', 'Stock Release to Staff'),
        ('RETURN', 'Returned to Safe'),
    )

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()

    movement_type = models.CharField(max_length=10, choices=MOVEMENT_TYPE)
    performed_by = models.ForeignKey(User, on_delete=models.CASCADE)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.model_name} - {self.movement_type}"

class MultiChoiceSale(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)

    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20, null=True, blank=True)
    iuc_number = models.CharField(max_length=100, null=True, blank=True)
    service_type = models.CharField(max_length=20, choices=(("DSTV", "DSTV"), ("GOTV", "GOTV")), default="DSTV")
    package_type = models.CharField(max_length=100)
    transaction_type = models.CharField(
        max_length=20,
        choices=(
            ("NEW", "New Subscription"),
            ("RENEWAL", "Renewal"),
            ("UPGRADE", "Upgrade"),
        )
    )

    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer_name} - {self.package_type}"


class MultiChoiceWeeklyReport(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    week_start_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    additional_funds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_subscriptions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_closed = models.BooleanField(default=False)

    def calculate_commission(self):
        if self.closing_balance is not None:
            self.commission = (self.closing_balance + self.total_subscriptions) - (self.opening_balance + self.additional_funds)
            return self.commission
        return 0


class MultiChoiceBalance(models.Model):
    weekly_report = models.ForeignKey(MultiChoiceWeeklyReport, on_delete=models.CASCADE, related_name='balance_history')
    balance_amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after_sale = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sale_cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)
    notes = models.CharField(max_length=200, blank=True, null=True)
    is_commission_payment = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date', '-time']

    def __str__(self):
        return f"{self.weekly_report.staff.username} - ₦{self.balance_amount} on {self.date}"


class CommissionPayment(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    balance_record = models.ForeignKey(MultiChoiceBalance, on_delete=models.SET_NULL, null=True, blank=True)
    
    previous_balance = models.DecimalField(max_digits=12, decimal_places=2)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2)
    commission_detected = models.DecimalField(max_digits=12, decimal_places=2)
    
    date_detected = models.DateTimeField(auto_now_add=True)
    date_paid = models.DateField(null=True, blank=True)
    
    is_confirmed = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.staff.username} - ₦{self.commission_detected} on {self.date_detected}"


class RetailSale(models.Model):
    PAYMENT_METHODS = (
        ('CASH', 'Cash'),
        ('TRANSFER', 'Transfer'),
        ('POS', 'POS'),
    )
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    customer_phone = models.CharField(max_length=20, null=True, blank=True)

    quantity = models.PositiveIntegerField()
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    color = models.CharField(max_length=50, blank=True, null=True, help_text="Color variant sold")
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='CASH')

    is_voided   = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True, default="")
    voided_by   = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True, related_name="voided_sales")
    voided_at   = models.DateTimeField(null=True, blank=True)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["branch"]),
            models.Index(fields=["staff"]),
        ]

    def total_amount(self):
        return self.quantity * self.selling_price

    def __str__(self):
        return f"{self.product.model_name} - {self.quantity} sold by {self.staff.username}"


class StockRequest(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    date_requested = models.DateField(auto_now_add=True)


# -----------------------
# Customer CRM
# -----------------------
class Customer(models.Model):
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, unique=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    purchase_count = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_purchase = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.phone_number}"


class StockAlert(models.Model):
    ALERT_TYPES = (
        ('LOW_STOCK', 'Low Stock'),
        ('OUT_OF_STOCK', 'Out of Stock'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    threshold = models.IntegerField()
    current_quantity = models.IntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.model_name} - {self.alert_type}"


class MultiChoiceHardwareStock(models.Model):
    """A MultiChoice staff member's personal decoder/accessory inventory."""
    ITEM_CHOICES = [
        ('GOTV_DECODER_SET', 'Complete GOtv Decoder Set'),
        ('DSTV_DECODER_SET', 'Complete DStv Decoder Set'),
        ('SINGLE_DECODER',   'Single Decoder'),
        ('REMOTE',           'Remote'),
        ('ADAPTER',          'Adapter'),
        ('ANTENNA',          'Antenna'),
        ('WIRE',             'Wire'),
        ('OTHER',            'Other'),
    ]
    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='mc_hardware_stock')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='mc_hardware_stock')
    item_type = models.CharField(max_length=20, choices=ITEM_CHOICES)
    other_description = models.CharField(max_length=150, blank=True, default='')
    quantity = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('staff', 'item_type', 'other_description')

    def __str__(self):
        label = self.other_description if self.item_type == 'OTHER' else self.get_item_type_display()
        return f"{self.staff.username} - {label} ({self.quantity})"


class MultiChoiceHardwareSale(models.Model):
    """A hardware sale (decoder, accessory) recorded by a MultiChoice staff member."""
    ITEM_CHOICES = MultiChoiceHardwareStock.ITEM_CHOICES

    staff = models.ForeignKey('User', on_delete=models.CASCADE, related_name='mc_hardware_sales')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='mc_hardware_sales')
    item_type = models.CharField(max_length=20, choices=ITEM_CHOICES)
    other_description = models.CharField(max_length=150, blank=True, default='')
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    iuc_number = models.CharField(max_length=30, blank=True, default='')
    customer_name = models.CharField(max_length=150, blank=True, default='')
    customer_phone = models.CharField(max_length=20, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        label = self.other_description if self.item_type == 'OTHER' else self.get_item_type_display()
        return f"{label} x{self.quantity} - {self.staff.username}"


class MonthlyPerformanceArchive(models.Model):
    """A permanently-stored snapshot of one month's performance, per branch
    and company-wide (branch=NULL). Once a month is archived here, its
    numbers don't change -- this is the historical record for
    month-to-month comparison."""
    month = models.DateField(help_text="Always the 1st of the archived month")
    branch = models.ForeignKey(
        'Branch', on_delete=models.CASCADE, null=True, blank=True,
        related_name='monthly_archives',
        help_text="Null = company-wide total row for this month"
    )
    retail_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retail_quantity = models.IntegerField(default=0)
    retail_gross_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_quantity = models.IntegerField(default=0)
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_profit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    new_customers = models.IntegerField(default=0)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('month', 'branch')
        ordering = ['-month']

    def __str__(self):
        scope = self.branch.name if self.branch else "Company-wide"
        return f"{scope} - {self.month.strftime('%B %Y')}"


class StaffMonthlyPerformanceArchive(models.Model):
    """A permanently-stored snapshot of one staff member's performance for
    one month -- their historical record, independent of the raw sales
    tables, and the source for their monthly emailed report."""
    staff = models.ForeignKey(
        'User', on_delete=models.CASCADE, related_name='monthly_archives'
    )
    month = models.DateField(help_text="Always the 1st of the archived month")
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)

    retail_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    retail_quantity = models.IntegerField(default=0)
    multichoice_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    multichoice_quantity = models.IntegerField(default=0)
    hardware_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    hardware_quantity = models.IntegerField(default=0)
    online_sales_count = models.IntegerField(default=0)
    online_sales_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    telecom_activity_count = models.IntegerField(default=0)

    days_present = models.IntegerField(default=0)
    days_late = models.IntegerField(default=0)
    days_absent = models.IntegerField(default=0)

    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('staff', 'month')
        ordering = ['-month']

    @property
    def total_revenue(self):
        return (self.retail_revenue or 0) + (self.multichoice_revenue or 0) + \
               (self.hardware_revenue or 0) + (self.online_sales_revenue or 0)

    def __str__(self):
        return f"{self.staff.username} - {self.month.strftime('%B %Y')}"


class DeviceTagCommission(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE)
    month_year = models.CharField(max_length=7)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('device_tag', 'month_year')

    def __str__(self):
        return f"{self.device_tag.tag_name} - {self.month_year}"


class CheckInOutLog(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    check_in_time = models.DateTimeField()
    check_out_time = models.DateTimeField(null=True, blank=True)
    purpose = models.CharField(max_length=200, null=True, blank=True)
    is_checkout = models.BooleanField(default=False)
    date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.staff.username} - {self.date}"


class Attendance(models.Model):
    SESSION_CHOICES = (
        ("morning", "Morning"),
        ("evening", "Evening"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    session = models.CharField(max_length=10, choices=SESSION_CHOICES)
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    distance_from_branch = models.FloatField(default=0)
    selfie = models.ImageField(upload_to="attendance_selfies/")
    date = models.DateField(default=timezone.now)
    is_late = models.BooleanField(default=False)
    is_absent = models.BooleanField(default=False)
    deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"{self.user.username} - {self.date}"



class SimInventory(models.Model):
    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name='sim_inventory')
    opening_balance = models.IntegerField(default=0)
    current_month = models.IntegerField(default=0)
    current_year = models.IntegerField(default=0)
    total_received = models.IntegerField(default=0)
    total_sold = models.IntegerField(default=0)
    date_updated = models.DateTimeField(auto_now=True)

    def get_current_balance(self):
        return self.opening_balance + self.total_received - self.total_sold

    def __str__(self):
        return f"{self.branch.name} SIM Inventory - Balance: {self.get_current_balance()}"



class SimInventoryLog(models.Model):
    TRANSACTION_TYPE = (
        ('OPENING', 'Opening Balance'),
        ('RECEIVED', 'SIM Received'),
        ('SOLD', 'SIM Sold/Used'),
    )

    inventory = models.ForeignKey(SimInventory, on_delete=models.CASCADE, related_name='logs')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE)
    quantity = models.IntegerField()
    description = models.TextField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.inventory.branch.name} - {self.transaction_type}: {self.quantity} SIMs"



# ─────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────

class AuditLog(models.Model):
    ACTION_CHOICES = (
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
        ('VOID',   'Voided'),
        ('LOGIN',  'Logged In'),
    )
    user        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action      = models.CharField(max_length=10, choices=ACTION_CHOICES)
    model_name  = models.CharField(max_length=100)
    object_id   = models.IntegerField(null=True, blank=True)
    description = models.TextField()
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    timestamp   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes  = [models.Index(fields=['model_name', 'timestamp'])]

    def __str__(self):
        return f"{self.user} — {self.action} {self.model_name} at {self.timestamp:%d %b %Y %H:%M}"



def log_action(user, action, model_name, obj_id=None, description='', request=None):
    ip = None
    if request:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = x_forwarded.split(',')[0] if x_forwarded else request.META.get('REMOTE_ADDR')
    AuditLog.objects.create(
        user=user, action=action, model_name=model_name,
        object_id=obj_id, description=description, ip_address=ip,
    )


# ─────────────────────────────────────────
# NOTIFICATION
# ─────────────────────────────────────────

class Notification(models.Model):
    TYPE_CHOICES = (
        ('STOCK_REQUEST',  'Stock Request'),
        ('LOW_STOCK',      'Low Stock Alert'),
        ('APPROVAL',       'Pending Approval'),
        ('VOID',           'Sale Voided'),
        ('GENERAL',        'General'),
    )
    recipient   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notif_type  = models.CharField(max_length=20, choices=TYPE_CHOICES, default='GENERAL')
    title       = models.CharField(max_length=200)
    message     = models.TextField()
    link        = models.CharField(max_length=200, blank=True)
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.recipient.username} — {self.title}"



def notify_user(recipient, title, message, notif_type='GENERAL', link=''):
    Notification.objects.create(
        recipient=recipient, title=title, message=message,
        notif_type=notif_type, link=link,
    )


def notify_role(role, title, message, notif_type='GENERAL', link='', branch=None):
    qs = User.objects.filter(role=role)
    if branch:
        qs = qs.filter(branch=branch)
    for user in qs:
        Notification.objects.create(
            recipient=user, title=title, message=message,
            notif_type=notif_type, link=link,
        )


# ─────────────────────────────────────────
# SUPPLIER & PURCHASE ORDER
# ─────────────────────────────────────────

class Supplier(models.Model):
    name       = models.CharField(max_length=200)
    phone      = models.CharField(max_length=20, blank=True)
    email      = models.EmailField(blank=True)
    address    = models.TextField(blank=True)
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name



class PurchaseOrder(models.Model):
    STATUS_CHOICES = (
        ('PENDING',   'Pending'),
        ('RECEIVED',  'Received'),
        ('CANCELLED', 'Cancelled'),
    )
    supplier     = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='orders')
    branch       = models.ForeignKey('Branch', on_delete=models.CASCADE)
    ordered_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='purchase_orders')
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes        = models.TextField(blank=True)
    date_ordered = models.DateField(auto_now_add=True)
    date_received= models.DateField(null=True, blank=True)

    def __str__(self):
        return f"PO#{self.id} — {self.supplier.name} ({self.status})"



class PurchaseOrderItem(models.Model):
    order    = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product  = models.ForeignKey('Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_cost= models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost

    def __str__(self):
        return f"{self.product.model_name} x{self.quantity}"


# ─────────────────────────────────────────
# WHOLESALE DEVICE CATALOG (MiFi, Routers, SIMs)
# Add these classes to core/models.py
# ─────────────────────────────────────────

class WholesaleDevice(models.Model):
    PRODUCT_TYPE_CHOICES = (
        ('SIM',    'SIM Card'),
        ('MIFI',   'MiFi Device'),
        ('ROUTER', 'Router'),
        ('OTHER',  'Other Device'),
    )
    NETWORK_CHOICES = (
        ('4G', '4G LTE'),
        ('5G', '5G'),
        ('ANY', 'Any/Not Applicable'),
    )

    branch       = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='wholesale_devices')
    staff        = models.ForeignKey('User', on_delete=models.CASCADE, related_name='wholesale_devices')
    product_name = models.CharField(max_length=200)
    product_type = models.CharField(max_length=10, choices=PRODUCT_TYPE_CHOICES, default='MIFI')
    network_type = models.CharField(max_length=5, choices=NETWORK_CHOICES, default='4G')
    serial_number= models.CharField(max_length=100, blank=True)
    quantity     = models.PositiveIntegerField(default=0)
    cost_price   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    selling_price= models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes        = models.TextField(blank=True)
    date_added   = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_added']
        indexes  = [models.Index(fields=['branch', 'staff'])]

    def __str__(self):
        return f"{self.product_name} ({self.network_type}) — {self.branch.name}"

    @property
    def total_value(self):
        return self.quantity * self.selling_price


class Invoice(models.Model):
    SALE_TYPES = (
        ('RETAIL', 'Retail Sale'),
        ('MULTICHOICE', 'MultiChoice Subscription'),
        ('TELECOM', 'Telecom Service'),
        ('WHOLESALE', 'Wholesale Device'),
    )

    invoice_number = models.CharField(max_length=50, unique=True)
    sale_type      = models.CharField(max_length=20, choices=SALE_TYPES)
    sale_id        = models.PositiveIntegerField()

    branch         = models.ForeignKey(Branch, on_delete=models.CASCADE)
    staff          = models.ForeignKey(User, on_delete=models.CASCADE)

    customer_name  = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)

    product_description = models.CharField(max_length=300, blank=True)
    quantity       = models.PositiveIntegerField(default=1)
    unit_price     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, blank=True)

    date           = models.DateField(auto_now_add=True)
    time           = models.TimeField(auto_now_add=True)
    generated_at   = models.DateTimeField(auto_now_add=True)
    emailed_to     = models.EmailField(blank=True, null=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"{self.invoice_number} — {self.sale_type} — ₦{self.total_amount}"


class WholesaleDeviceSale(models.Model):
    BUYER_TYPE_CHOICES = (
        ('CUSTOMER', 'Customer'),
        ('DIRECTOR', 'Director'),
        ('BRANCH',   'Branch Transfer'),
    )

    device       = models.ForeignKey(WholesaleDevice, on_delete=models.CASCADE, related_name='sales')
    sold_by      = models.ForeignKey('User', on_delete=models.CASCADE, related_name='wholesale_sales')
    branch       = models.ForeignKey('Branch', on_delete=models.CASCADE)
    buyer_type   = models.CharField(max_length=10, choices=BUYER_TYPE_CHOICES, default='CUSTOMER')
    buyer_name   = models.CharField(max_length=200, blank=True)
    buyer_phone  = models.CharField(max_length=20, blank=True)
    quantity     = models.PositiveIntegerField()
    unit_price   = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=(
        ('CASH', 'Cash'), ('TRANSFER', 'Transfer'), ('POS', 'POS')
    ), default='CASH')
    is_director_sale = models.BooleanField(default=False)
    notes        = models.TextField(blank=True)
    date         = models.DateField(auto_now_add=True)
    time         = models.TimeField(auto_now_add=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.device.product_name} x{self.quantity} → {self.buyer_type} ({self.branch.name})"


# ────────────────────────────────────────────
# Moniepoint POS Transaction Tracking
# ────────────────────────────────────────────

class MoniepointTransaction(models.Model):
    """Track Moniepoint POS transactions for reconciliation."""
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REVERSED', 'Reversed'),
    )

    transaction_id = models.CharField(max_length=100, unique=True, help_text="Moniepoint Transaction ID")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True)
    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Link to original sale (optional)
    sale_type = models.CharField(max_length=20, blank=True, help_text="RETAIL, WHOLESALE, MULTICHOICE, TELECOM")
    sale_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['branch', 'date']),
            models.Index(fields=['status']),
            models.Index(fields=['transaction_id']),
        ]

    def __str__(self):
        return f"Moniepoint {self.transaction_id} — ₦{self.amount} ({self.status})"


# ────────────────────────────────────────────
# Loyalty & Rewards Program
# ────────────────────────────────────────────

class LoyaltyPoint(models.Model):
    """Tracks points earned per customer per branch."""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='loyalty_points')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    points_balance = models.PositiveIntegerField(default=0)
    total_earned = models.PositiveIntegerField(default=0)
    total_redeemed = models.PositiveIntegerField(default=0)
    tier = models.CharField(max_length=20, default='BRONZE', choices=(
        ('BRONZE', 'Bronze'),
        ('SILVER', 'Silver'),
        ('GOLD', 'Gold'),
        ('PLATINUM', 'Platinum'),
    ))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('customer', 'branch')

    def __str__(self):
        return f"{self.customer.phone_number} — {self.points_balance} pts ({self.tier})"

    def update_tier(self):
        """Auto-update tier based on total earned."""
        if self.total_earned >= 50000:
            self.tier = 'PLATINUM'
        elif self.total_earned >= 20000:
            self.tier = 'GOLD'
        elif self.total_earned >= 5000:
            self.tier = 'SILVER'
        else:
            self.tier = 'BRONZE'
        self.save(update_fields=['tier'])


class LoyaltyTransaction(models.Model):
    """Individual point earn/redeem transactions."""
    TYPE_CHOICES = (
        ('EARN', 'Earned'),
        ('REDEEM', 'Redeemed'),
        ('ADJUST', 'Adjustment'),
        ('EXPIRE', 'Expired'),
    )

    loyalty_point = models.ForeignKey(LoyaltyPoint, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    points = models.PositiveIntegerField()
    amount_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.CharField(max_length=255, blank=True)
    sale_type = models.CharField(max_length=20, blank=True)
    sale_id = models.IntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} {self.points} pts — {self.loyalty_point.customer.phone_number}"


# ─────────────────────────────────────────
# PRICE FLOOR — prevents selling below minimum
# ─────────────────────────────────────────

class PriceFloor(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='price_floors')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='price_floors')
    min_selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        unique_together = [['product', 'branch']]
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.product.model_name} @ {self.branch.name} — min ₦{self.min_selling_price}"


# ─────────────────────────────────────────
# CHANGE LOG — every data change recorded
# ─────────────────────────────────────────

class ChangeLog(models.Model):
    ACTION_CHOICES = (
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
        ('VOID', 'Voided'),
        ('SALE', 'Sale Recorded'),
        ('STOCK_IN', 'Stock Added'),
        ('STOCK_OUT', 'Stock Released'),
        ('PRICE_CHANGE', 'Price Changed'),
        ('CHECK_IN', 'Checked In'),
        ('CHECK_OUT', 'Checked Out'),
        ('APPROVE', 'Approved'),
        ('REJECT', 'Rejected'),
        ('BACKUP', 'Backup Run'),
        ('RESET', 'Monthly Reset'),
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100)
    object_id = models.IntegerField(null=True, blank=True)
    description = models.TextField()
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['model_name', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['branch', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user or 'System'} — {self.action} {self.model_name} at {self.timestamp:%d %b %H:%M}"


# ─────────────────────────────────────────
# BACKUP LOG — tracks backup runs
# ─────────────────────────────────────────

class BackupLog(models.Model):
    STATUS_CHOICES = (
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partial'),
    )
    triggered_by = models.CharField(max_length=50, default='auto')  # auto, manual, cron
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    file_path = models.CharField(max_length=500, blank=True)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    email_recipient = models.EmailField(blank=True)
    email_error = models.TextField(blank=True)
    supabase_uploaded = models.BooleanField(default=False)
    supabase_error = models.TextField(blank=True)
    record_count = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Backup {self.status} — {self.started_at:%d %b %Y %H:%M}"


# ─────────────────────────────────────────
# DIRECTOR DAILY DIGEST — tracks sent digests
# ─────────────────────────────────────────

class DirectorDailyDigest(models.Model):
    date = models.DateField(unique=True)
    email_sent = models.BooleanField(default=False)
    email_recipient = models.EmailField(blank=True)
    email_error = models.TextField(blank=True)
    total_retail_sales = models.IntegerField(default=0)
    total_retail_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_multichoice_sales = models.IntegerField(default=0)
    total_multichoice_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_service_activities = models.IntegerField(default=0)
    total_new_customers = models.IntegerField(default=0)
    total_stock_alerts = models.IntegerField(default=0)
    total_attendance_records = models.IntegerField(default=0)
    total_expenses = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Digest {self.date} — {'Sent' if self.email_sent else 'Pending'}"


# ─────────────────────────────────────────
# MONTHLY RESET LOG — tracks data resets
# ─────────────────────────────────────────

class MonthlyResetLog(models.Model):
    year = models.IntegerField()
    month = models.IntegerField()
    reset_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reset_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [['year', 'month']]
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Reset {self.year}-{self.month:02d} — {self.reset_at:%d %b %Y}"



# ─────────────────────────────────────────
# Add these classes to core/models.py
# Landing page - Slideshow and Product Catalog
# ─────────────────────────────────────────

class SlideShowItem(models.Model):
    """Hero carousel slides on the landing page."""
    title       = models.CharField(max_length=200)
    subtitle    = models.CharField(max_length=300, blank=True)
    image       = models.ImageField(upload_to='slideshow/', blank=True, null=True)
    image_url   = models.URLField(blank=True, help_text="Or paste an external image URL")
    badge_text  = models.CharField(max_length=50, blank=True, help_text="e.g. NEW, HOT DEAL, LIMITED")
    price       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    old_price   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Original price before discount")
    cta_text    = models.CharField(max_length=50, default="Order on WhatsApp", help_text="Button text")
    whatsapp_msg = models.TextField(blank=True, help_text="Pre-filled WhatsApp message. Leave blank to auto-generate.")
    is_active   = models.BooleanField(default=True)
    order       = models.PositiveIntegerField(default=0, help_text="Display order (lower = first)")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', '-created_at']
        verbose_name = "Slideshow Item"
        verbose_name_plural = "Slideshow Items"

    def __str__(self):
        return self.title

    @property
    def discount_percent(self):
        if self.old_price and self.price and self.old_price > self.price:
            return round((1 - self.price / self.old_price) * 100)
        return None

    @property
    def get_image_url(self):
        if self.image:
            return self.image.url
        return self.image_url or ''


class CatalogCategory(models.Model):
    """Categories for the public catalog."""
    name  = models.CharField(max_length=100)
    icon  = models.CharField(max_length=10, blank=True, help_text="Emoji icon e.g. 📱")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Catalog Category"
        verbose_name_plural = "Catalog Categories"

    def __str__(self):
        return self.name


class CatalogProduct(models.Model):
    """Products shown on the public landing page catalog."""
    CONDITION_CHOICES = (
        ('NEW',   'Brand New'),
        ('UK',    'UK Used'),
        ('LOCAL', 'Nigerian Used'),
    )
    category     = models.ForeignKey(CatalogCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    name         = models.CharField(max_length=200)
    description  = models.TextField(blank=True)
    image        = models.ImageField(upload_to='catalog/', blank=True, null=True)
    image_url    = models.URLField(blank=True, help_text="Or paste an external image URL")
    price        = models.DecimalField(max_digits=12, decimal_places=2)
    old_price    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    badge        = models.CharField(max_length=50, blank=True, help_text="e.g. HOT, NEW, SOLD OUT")
    condition    = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='NEW')
    is_available = models.BooleanField(default=True)
    is_featured  = models.BooleanField(default=False, help_text="Show in featured section")
    whatsapp_msg = models.TextField(blank=True, help_text="Pre-filled WhatsApp message. Leave blank to auto-generate.")
    order        = models.PositiveIntegerField(default=0)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', '-created_at']
        verbose_name = "Catalog Product"
        verbose_name_plural = "Catalog Products"

    def __str__(self):
        return self.name

    @property
    def discount_percent(self):
        if self.old_price and self.price and self.old_price > self.price:
            return round((1 - self.price / self.old_price) * 100)
        return None

    @property
    def get_image_url(self):
        if self.image:
            return self.image.url
        return self.image_url or 'https://placehold.co/400x400/004F9F/FFCB05?text=GPSL'

    @property
    def whatsapp_text(self):
        if self.whatsapp_msg:
            return self.whatsapp_msg
        price_str = f"₦{self.price:,.0f}"
        return (
            f"Hello GPSL! I'm interested in:\n\n"
            f"*{self.name}*\n"
            f"Price: {price_str}\n"
            f"Condition: {self.get_condition_display()}\n\n"
            f"Is this available? Please let me know. Thank you!"
        )


class RouterSubscription(models.Model):
    """
    Tracks 4G/5G Router subscriptions sold by Telecom staff.
    Policy: every router sale must have 2 months subscription recorded.
    Each month = 30 days. Staff must renew before expiry.
    """
    ROUTER_TYPE_CHOICES = [
        ('4G', '4G Router'),
        ('5G', '5G Router'),
    ]
    staff             = models.ForeignKey('User', on_delete=models.CASCADE, related_name='router_subs')
    branch            = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='router_subs')
    customer_name     = models.CharField(max_length=150)
    customer_phone    = models.CharField(max_length=20)
    alt_phone         = models.CharField(max_length=20, blank=True, default='')
    router_number     = models.CharField(max_length=100, help_text='Router serial / SIM number')
    router_type       = models.CharField(max_length=20, choices=ROUTER_TYPE_CHOICES, default='4G')
    network           = models.CharField(max_length=50, blank=True, default='MTN')
    subscription_date = models.DateField(null=True, blank=True)
    expiry_date       = models.DateField(null=True, blank=True, help_text='Auto-set to subscription_date + 30 days')
    month_number      = models.PositiveIntegerField(default=1, help_text='1 = first month, 2 = second month')
    amount            = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active         = models.BooleanField(default=True)
    notes             = models.TextField(blank=True, default='')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expiry_date']
        verbose_name = 'Router Subscription'
        verbose_name_plural = 'Router Subscriptions'

    def save(self, *args, **kwargs):
        from datetime import date, timedelta
        if not self.subscription_date:
            self.subscription_date = date.today()
        if not self.expiry_date:
            self.expiry_date = self.subscription_date + timedelta(days=30)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer_name} — {self.router_number} (expires {self.expiry_date})"

    @property
    def days_to_expiry(self):
        from datetime import date
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return 999

    @property
    def is_expired(self):
        return self.days_to_expiry < 0

    @property
    def expiry_status(self):
        days = self.days_to_expiry
        if days < 0: return 'expired'
        if days <= 3: return 'critical'
        if days <= 7: return 'warning'
        return 'active'


class StockTransfer(models.Model):
    """Stock movement between Director Safe, Branch Safe, Staff Stock."""
    TRANSFER_TYPE_CHOICES = [
        ('DIRECTOR_TO_BRANCH',  'Director Safe → Branch Safe'),
        ('BRANCH_TO_BRANCH',    'Branch → Branch'),
        ('BRANCH_TO_STAFF',     'Branch Safe → Staff Stock'),
        ('STAFF_TO_BRANCH',     'Staff Stock → Branch Safe'),
        ('BRANCH_TO_DIRECTOR',  'Branch Safe → Director Safe'),
    ]
    transfer_type  = models.CharField(max_length=30, choices=TRANSFER_TYPE_CHOICES)
    product        = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='transfers')
    quantity       = models.PositiveIntegerField()
    notes          = models.TextField(blank=True, default='')
    from_branch    = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_out')
    to_branch      = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_in')
    to_staff       = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_received')
    initiated_by   = models.ForeignKey('User', on_delete=models.CASCADE, related_name='transfers_initiated')
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Stock Transfer'
        verbose_name_plural = 'Stock Transfers'

    def __str__(self):
        return f"{self.product.model_name} x{self.quantity} ({self.get_transfer_type_display()})"

    @property
    def source_label(self):
        if self.from_branch:
            return self.from_branch.name
        return "Director Safe"

    @property
    def destination_label(self):
        if self.to_branch:
            return self.to_branch.name
        if self.to_staff:
            return f"{self.to_staff.username} (Staff)"
        return "Director Safe"


class OnlineSaleLog(models.Model):
    """
    Staff online/social media sales log.
    Any staff member can log a sale made via social media.
    Director sees all logs with leaderboard.
    """
    PLATFORM_CHOICES = [
        ('whatsapp',   'WhatsApp'),
        ('facebook',   'Facebook'),
        ('instagram',  'Instagram'),
        ('tiktok',     'TikTok'),
        ('twitter',    'Twitter/X'),
        ('referral',   'Referral'),
        ('other',      'Other'),
    ]

    staff            = models.ForeignKey('User', on_delete=models.CASCADE, related_name='online_sales')
    branch           = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='online_sales')
    product_name     = models.CharField(max_length=200, help_text='Name of product/service sold')
    customer_name    = models.CharField(max_length=150)
    customer_phone   = models.CharField(max_length=20)
    platform         = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='whatsapp')
    amount           = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_date        = models.DateField()
    evidence_image   = models.ImageField(
        upload_to='online_sales/', null=True, blank=True,
        help_text='Screenshot or photo evidence of sale'
    )
    notes            = models.TextField(blank=True, default='')
    is_verified      = models.BooleanField(default=False, help_text='Director/Manager verified this sale')
    verified_by      = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_online_sales'
    )
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_date', '-created_at']
        verbose_name = 'Online Sale Log'
        verbose_name_plural = 'Online Sale Logs'

    def __str__(self):
        return f"{self.staff.username} — {self.product_name} ({self.sale_date})"

    @property
    def image_url(self):
        try:
            if self.evidence_image:
                return self.evidence_image.url
        except Exception:
            pass
        return None
