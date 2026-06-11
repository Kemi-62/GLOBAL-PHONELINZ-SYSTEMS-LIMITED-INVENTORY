import os
import tempfile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from decimal import Decimal

from core.models import (
    Branch, Product, BranchSafeStock, StaffStock,
    RetailSale, MultiChoiceSale, RetailCategory,
    RetailSubCategory,
    MultiChoiceWeeklyReport, MultiChoiceBalance,
    DeviceTag, ServiceTarget, ServiceActivity,
)

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SalesTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Test Branch", allowed_radius=100)
        self.manager = User.objects.create_user(
            username="testmanager", password="testpass123", role="MANAGER", branch=self.branch
        )
        self.retail = User.objects.create_user(
            username="testretail", password="testpass123", role="RETAIL", branch=self.branch
        )
        self.multichoice = User.objects.create_user(
            username="testmc", password="testpass123", role="MULTICHOICE", branch=self.branch
        )
        self.telecom = User.objects.create_user(
            username="testtelecom", password="testpass123", role="TELECOM", branch=self.branch
        )
        self.category = RetailCategory.objects.create(name="Phones")
        self.sub = RetailSubCategory.objects.create(name="Smartphones", category=self.category)
        self.product = Product.objects.create(
            model_name="iPhone 15", imei_serial="ABC123", subcategory=self.sub,
            cost_price=Decimal("500.00"), selling_price=Decimal("700.00")
        )
        self.safe_stock = BranchSafeStock.objects.create(
            branch=self.branch, product=self.product, quantity=10
        )
        self.staff_stock = StaffStock.objects.create(
            staff=self.retail, product=self.product, quantity=3
        )
        self.client.login(username="testretail", password="testpass123")

    def test_retail_sale_creates(self):
        self.client.login(username="testretail", password="testpass123")
        resp = self.client.post(reverse("record_retail_sale"), {
            "product": str(self.product.id),
            "quantity": "1",
            "selling_price": "700.00",
            "payment_method": "CASH",
            "customer_phone": "08012345678",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(RetailSale.objects.filter(staff=self.retail).exists())
        sale = RetailSale.objects.first()
        self.assertEqual(sale.quantity, 1)
        self.assertEqual(sale.selling_price, Decimal("700.00"))

    def test_retail_sale_deducts_stock(self):
        self.client.login(username="testretail", password="testpass123")
        self.client.post(reverse("record_retail_sale"), {
            "product": str(self.product.id),
            "quantity": "2",
            "selling_price": "700.00",
            "payment_method": "CASH",
        })
        self.staff_stock.refresh_from_db()
        self.assertEqual(self.staff_stock.quantity, 1)

    def test_multichoice_sale_creates(self):
        self.client.login(username="testmc", password="testpass123")
        resp = self.client.post(reverse("record_multichoice_sale"), {
            "service_type": "DSTV",
            "package": "Compact",
            "cost": "5000",
            "amount": "7000",
            "customer_phone": "08012345678",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(MultiChoiceSale.objects.filter(staff=self.multichoice).exists())

    def test_multichoice_weekly_report(self):
        self.client.login(username="testmc", password="testpass123")
        report = MultiChoiceWeeklyReport.objects.create(
            staff=self.multichoice, branch=self.branch,
            week_start_date="2026-06-01", opening_balance=Decimal("10000.00")
        )
        self.client.post(reverse("record_balance"), {
            "current_balance": "5000.00",
            "notes": "Test",
        })
        self.assertTrue(MultiChoiceBalance.objects.filter(weekly_report=report).exists())

    def test_service_activity(self):
        self.client.login(username="testtelecom", password="testpass123")
        tag = DeviceTag.objects.create(branch=self.branch, tag_name="SIM-A")
        target = ServiceTarget.objects.create(
            branch=self.branch, service_type="SIM_REG", device_tag=tag,
            target_number=10, date="2026-06-11", created_by=self.manager
        )
        resp = self.client.post(reverse("staff_dashboard"), {
            "service_type": "SIM_REG",
            "device_tag": str(tag.id),
            "quantity": "5",
            "date": "2026-06-11",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ServiceActivity.objects.filter(staff=self.telecom).exists())

    def test_retail_sale_void(self):
        self.client.login(username="testmanager", password="testpass123")
        sale = RetailSale.objects.create(
            branch=self.branch, staff=self.retail, product=self.product,
            quantity=1, selling_price=Decimal("700.00"), payment_method="CASH",
            date="2026-06-11"
        )
        resp = self.client.post(reverse("void_sale", args=[sale.id]))
        self.assertEqual(resp.status_code, 302)
        sale.refresh_from_db()
        self.assertTrue(sale.is_voided)
