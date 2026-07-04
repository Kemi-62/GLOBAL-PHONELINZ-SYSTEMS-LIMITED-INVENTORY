
# ─────────────────────────────────────────
# ADD TO core/admin.py
# ─────────────────────────────────────────

ADMIN_CODE = '''
from core.models import SlideShowItem, CatalogCategory, CatalogProduct

@admin.register(SlideShowItem)
class SlideShowItemAdmin(admin.ModelAdmin):
    list_display  = ('title', 'price', 'old_price', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    list_filter   = ('is_active',)
    search_fields = ('title', 'subtitle')
    ordering      = ('order',)

@admin.register(CatalogCategory)
class CatalogCategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'icon', 'order')
    list_editable = ('order',)

@admin.register(CatalogProduct)
class CatalogProductAdmin(admin.ModelAdmin):
    list_display  = ('name', 'category', 'price', 'old_price', 'condition', 'is_available', 'is_featured', 'order')
    list_editable = ('is_available', 'is_featured', 'order')
    list_filter   = ('category', 'condition', 'is_available', 'is_featured')
    search_fields = ('name', 'description')
    ordering      = ('order', '-created_at')
'''

# ─────────────────────────────────────────
# ADD TO core/views.py
# ERP Catalog Management views (Director only)
# ─────────────────────────────────────────

VIEWS_CODE = '''

@role_required("DIRECTOR")
def catalog_management(request):
    """Director page to manage landing page slideshow and products."""
    from core.models import SlideShowItem, CatalogCategory, CatalogProduct

    slides   = SlideShowItem.objects.all()
    cats     = CatalogCategory.objects.all()
    products = CatalogProduct.objects.select_related('category').all()

    return render(request, "director/catalog_management.html", {
        "slides": slides,
        "cats": cats,
        "products": products,
    })


@role_required("DIRECTOR")
def catalog_add_slide(request):
    from core.models import SlideShowItem
    if request.method == "POST":
        try:
            slide = SlideShowItem(
                title    = request.POST.get("title","").strip(),
                subtitle = request.POST.get("subtitle","").strip(),
                badge_text = request.POST.get("badge_text","").strip(),
                price    = request.POST.get("price") or None,
                old_price = request.POST.get("old_price") or None,
                cta_text = request.POST.get("cta_text","Order on WhatsApp").strip(),
                whatsapp_msg = request.POST.get("whatsapp_msg","").strip(),
                image_url = request.POST.get("image_url","").strip(),
                is_active = request.POST.get("is_active") == "on",
                order    = int(request.POST.get("order",0) or 0),
            )
            if "image" in request.FILES:
                slide.image = request.FILES["image"]
            slide.save()
            messages.success(request, f"Slide '{slide.title}' added.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_edit_slide(request, slide_id):
    from core.models import SlideShowItem
    slide = get_object_or_404(SlideShowItem, id=slide_id)
    if request.method == "POST":
        try:
            slide.title      = request.POST.get("title","").strip()
            slide.subtitle   = request.POST.get("subtitle","").strip()
            slide.badge_text = request.POST.get("badge_text","").strip()
            slide.price      = request.POST.get("price") or None
            slide.old_price  = request.POST.get("old_price") or None
            slide.cta_text   = request.POST.get("cta_text","Order on WhatsApp").strip()
            slide.whatsapp_msg = request.POST.get("whatsapp_msg","").strip()
            slide.image_url  = request.POST.get("image_url","").strip()
            slide.is_active  = request.POST.get("is_active") == "on"
            slide.order      = int(request.POST.get("order",0) or 0)
            if "image" in request.FILES:
                slide.image = request.FILES["image"]
            slide.save()
            messages.success(request, f"Slide updated.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_delete_slide(request, slide_id):
    from core.models import SlideShowItem
    if request.method == "POST":
        get_object_or_404(SlideShowItem, id=slide_id).delete()
        messages.success(request, "Slide deleted.")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_add_product(request):
    from core.models import CatalogProduct, CatalogCategory
    if request.method == "POST":
        try:
            cat_id = request.POST.get("category")
            cat    = CatalogCategory.objects.get(id=cat_id) if cat_id else None
            prod   = CatalogProduct(
                category    = cat,
                name        = request.POST.get("name","").strip(),
                description = request.POST.get("description","").strip(),
                price       = request.POST.get("price",0),
                old_price   = request.POST.get("old_price") or None,
                badge       = request.POST.get("badge","").strip(),
                condition   = request.POST.get("condition","NEW"),
                is_available = request.POST.get("is_available") == "on",
                is_featured = request.POST.get("is_featured") == "on",
                whatsapp_msg = request.POST.get("whatsapp_msg","").strip(),
                image_url   = request.POST.get("image_url","").strip(),
                order       = int(request.POST.get("order",0) or 0),
            )
            if "image" in request.FILES:
                prod.image = request.FILES["image"]
            prod.save()
            messages.success(request, f"Product '{prod.name}' added.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_edit_product(request, product_id):
    from core.models import CatalogProduct, CatalogCategory
    prod = get_object_or_404(CatalogProduct, id=product_id)
    if request.method == "POST":
        try:
            cat_id = request.POST.get("category")
            prod.category    = CatalogCategory.objects.get(id=cat_id) if cat_id else None
            prod.name        = request.POST.get("name","").strip()
            prod.description = request.POST.get("description","").strip()
            prod.price       = request.POST.get("price",0)
            prod.old_price   = request.POST.get("old_price") or None
            prod.badge       = request.POST.get("badge","").strip()
            prod.condition   = request.POST.get("condition","NEW")
            prod.is_available = request.POST.get("is_available") == "on"
            prod.is_featured = request.POST.get("is_featured") == "on"
            prod.whatsapp_msg = request.POST.get("whatsapp_msg","").strip()
            prod.image_url   = request.POST.get("image_url","").strip()
            prod.order       = int(request.POST.get("order",0) or 0)
            if "image" in request.FILES:
                prod.image = request.FILES["image"]
            prod.save()
            messages.success(request, "Product updated.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_delete_product(request, product_id):
    from core.models import CatalogProduct
    if request.method == "POST":
        get_object_or_404(CatalogProduct, id=product_id).delete()
        messages.success(request, "Product deleted.")
    return redirect("catalog_management")


@role_required("DIRECTOR")
def catalog_add_category(request):
    from core.models import CatalogCategory
    if request.method == "POST":
        name  = request.POST.get("name","").strip()
        icon  = request.POST.get("icon","").strip()
        order = int(request.POST.get("order",0) or 0)
        if name:
            CatalogCategory.objects.create(name=name, icon=icon, order=order)
            messages.success(request, f"Category '{name}' added.")
    return redirect("catalog_management")


def landing_page(request):
    """
    Root URL handler.
    globalphonelinz.com  -> landing page
    app.globalphonelinz.com -> redirect to login
    """
    from core.models import SlideShowItem, CatalogCategory, CatalogProduct
    host = request.get_host().lower()
    if 'app.' in host:
        return redirect('login')

    slides   = SlideShowItem.objects.filter(is_active=True).order_by('order')
    cats     = CatalogCategory.objects.all()
    featured = CatalogProduct.objects.filter(
        is_available=True, is_featured=True
    ).select_related('category').order_by('order')[:8]
    all_products = CatalogProduct.objects.filter(
        is_available=True
    ).select_related('category').order_by('order')

    # Seed placeholder slides if none exist
    if not slides.exists():
        SlideShowItem.objects.bulk_create([
            SlideShowItem(title="Latest iPhones — Best Prices in Uyo", subtitle="Brand new, sealed in box. All models available.", badge_text="NEW ARRIVAL", price=650000, old_price=720000, order=1),
            SlideShowItem(title="MTN SIM Registration — Fast & Easy", subtitle="Get your SIM registered in minutes. NIN linking available.", badge_text="FREE SERVICE", order=2),
            SlideShowItem(title="DStv & GOtv Subscriptions", subtitle="Renew or start a new subscription today at all branches.", badge_text="HOT DEAL", order=3),
        ])
        slides = SlideShowItem.objects.filter(is_active=True).order_by('order')

    # Seed placeholder categories if none exist
    if not cats.exists():
        CatalogCategory.objects.bulk_create([
            CatalogCategory(name="Phones", icon="📱", order=1),
            CatalogCategory(name="Accessories", icon="🎧", order=2),
            CatalogCategory(name="MiFi & Routers", icon="📡", order=3),
            CatalogCategory(name="DStv & GOtv", icon="📺", order=4),
        ])
        cats = CatalogCategory.objects.all()

    return render(request, "landing.html", {
        "slides": slides,
        "cats": cats,
        "featured": featured,
        "all_products": all_products,
        "whatsapp_number": "234XXXXXXXXXX",
    })
'''

print(ADMIN_CODE)
print(VIEWS_CODE)
