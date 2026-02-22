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
        ('staff', 'Staff'),
        ('manager', 'Manager'),
        ('director', 'Director'),
        ('super_admin', 'Super Admin'),
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
        