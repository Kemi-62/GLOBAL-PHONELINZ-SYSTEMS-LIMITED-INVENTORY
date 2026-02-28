from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models import Sum
from datetime import date

# -----------------------
# Branch
# -----------------------
class Branch(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return str(self.name)


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
class ServiceActivity(models.Model):
    SERVICE_CHOICES = (
        ('SIM_REG', 'SIM Registration'),
        ('SIM_SWAP', 'SIM Swap'),
        ('SIM_RET', 'SIM Retrieval'),
        ('NIN_LINK', 'NIN Linking'),
        ('MIFI', 'MiFi Sale'),
    )

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=50)
    device_tag = models.ForeignKey(DeviceTag, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    date = models.DateField(auto_now_add=True)

    approved = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.service_type != 'SIM_REG':
            self.device_tag = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_type} - {self.quantity}"

from django.conf import settings

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

class Product(models.Model):
    subsubcategory = models.ForeignKey(RetailSubSubCategory, on_delete=models.CASCADE, null=True, blank=True)
    subcategory = models.ForeignKey(RetailSubCategory, on_delete=models.CASCADE)
    product_name = models.CharField(max_length=200, null=True, blank=True)
    model_name = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    imei_last_5 = models.CharField(max_length=5, null=True, blank=True)

    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product_name or self.model_name} ({self.model_name})"

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
    package_type = models.CharField(max_length=100)
    transaction_type = models.CharField(
        max_length=20,
        choices=(
            ("NEW", "New Subscription"),
            ("RENEWAL", "Renewal"),
            ("UPGRADE", "Upgrade"),
        )
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer_name} - {self.package_type}"

class RetailSale(models.Model):
    staff = models.ForeignKey(User, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    quantity = models.PositiveIntegerField()
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def total_amount(self):
        return self.quantity * self.selling_price

    def __str__(self):
        return f"{self.product.model_name} - {self.quantity} sold by {self.staff.username}"
