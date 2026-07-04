
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
