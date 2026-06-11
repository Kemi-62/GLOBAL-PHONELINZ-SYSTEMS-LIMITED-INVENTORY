import os
import tempfile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal

from core.models import (
    Branch, Product, BranchSafeStock, StaffStock,
    StockRequest, StockMovement, StockAlert,
    RetailCategory, RetailSubCategory, RetailSubSubCategory,
    DirectorSafeStock,
)

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class StockTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Test Branch", allowed_radius=100)
        self.manager = User.objects.create_user(
            username="testmanager", password="testpass123", role="MANAGER", branch=self.branch
        )
        self.retail = User.objects.create_user(
            username="testretail", password="testpass123", role="RETAIL", branch=self.branch
        )
        self.director = User.objects.create_user(
            username="testdirector", password="testpass123", role="DIRECTOR"
        )
        self.director.is_superuser = True
        self.director.save()
        self.category = RetailCategory.objects.create(name="Phones")
        self.sub = RetailSubCategory.objects.create(name="Smartphones", category=self.category)
        self.subsub = RetailSubSubCategory.objects.create(name="Flagship", subcategory=self.sub)
        self.product = Product.objects.create(
            model_name="iPhone 15", imei_serial="ABC123",
            subcategory=self.sub, subsubcategory=self.subsub,
            cost_price=Decimal("500.00"), selling_price=Decimal("700.00"), color="Black"
        )
        self.safe_stock = BranchSafeStock.objects.create(
            branch=self.branch, product=self.product, quantity=10
        )

    def test_stock_request(self):
        self.client.login(username="testretail", password="testpass123")
        resp = self.client.post(reverse("request_stock"), {
            "product_name": "iPhone 15",
            "quantity": "2",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(StockRequest.objects.filter(staff=self.retail).exists())

    def test_release_stock(self):
        self.client.login(username="testmanager", password="testpass123")
        resp = self.client.post(reverse("release_stock"), {
            "staff": str(self.retail.id),
            "product": str(self.product.id),
            "quantity": "3",
        })
        self.assertEqual(resp.status_code, 302)
        self.safe_stock.refresh_from_db()
        self.assertEqual(self.safe_stock.quantity, 7)
        self.assertTrue(StaffStock.objects.filter(staff=self.retail, product=self.product).exists())

    def test_director_add_stock(self):
        self.client.login(username="testdirector", password="testpass123")
        resp = self.client.post(reverse("add_director_stock"), {
            "product_id": str(self.product.id),
            "quantity": "20",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(DirectorSafeStock.objects.filter(product=self.product).exists())

    def test_stock_alert(self):
        self.client.login(username="testmanager", password="testpass123")
        StockAlert.objects.create(branch=self.branch, product=self.product, threshold=3, current_quantity=2, alert_type="LOW_STOCK")
        resp = self.client.get(reverse("stock_alerts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Stock Alerts")

    def test_product_catalog(self):
        self.client.login(username="testretail", password="testpass123")
        resp = self.client.get(reverse("product_catalog"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "iPhone 15")

    def test_edit_staff_stock_price(self):
        self.client.login(username="testretail", password="testpass123")
        staff_stock = StaffStock.objects.create(
            staff=self.retail, product=self.product, quantity=2
        )
        resp = self.client.get(reverse("edit_staff_stock_price", args=[staff_stock.id]) + "?price=800.00")
        self.assertEqual(resp.status_code, 302)
        staff_stock.product.refresh_from_db()
        self.assertEqual(staff_stock.product.selling_price, Decimal("800.00"))

    def test_stock_movement_log(self):
        self.client.login(username="testmanager", password="testpass123")
        StockMovement.objects.create(
            branch=self.branch, product=self.product, quantity=5,
            movement_type="IN", date="2026-06-11", performed_by=self.manager
        )
        resp = self.client.get(reverse("stock_movement_log"))
        self.assertEqual(resp.status_code, 200)
