
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
