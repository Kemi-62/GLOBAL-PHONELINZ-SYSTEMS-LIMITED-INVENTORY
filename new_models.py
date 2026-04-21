from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


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
