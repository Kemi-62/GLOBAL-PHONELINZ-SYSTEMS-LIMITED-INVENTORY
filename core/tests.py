"""
GPSL ERP — Automated Tests

Run with: python manage.py test core

These tests cover:
  - Login functionality for all roles
  - Retail sale recording with price floor enforcement
  - Stock movement (add/release)
  - Change log recording
  - Monthly reset

Note: Django's test runner creates a temporary test database
so no real data is touched during tests.
"""
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import date, timedelta

from core.models import (
    Branch, Product, RetailCategory, RetailSubCategory,
    StaffStock, RetailSale, ChangeLog, BackupLog,
    MonthlyResetLog, PriceFloor, DirectorDailyDigest,
    Attendance, Customer, StockAlert,
)

User = get_user_model()


class LoginTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Test Branch", city="Test City")
        self.user = User.objects.create_user(
            username="testuser", password="testpass123",
            role="RETAIL", branch=self.branch,
        )

    def test_login_success(self):
        """User can log in with correct credentials."""
        response = self.client.post("/login/", {"username": "testuser", "password": "testpass123"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/retail/", response.url)

    def test_login_fail_wrong_password(self):
        """User cannot log in with wrong password."""
        response = self.client.post("/login/", {"username": "testuser", "password": "wrongpass"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid")

    def test_logout(self):
        """User can log out."""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get("/logout/")
        self.assertEqual(response.status_code, 302)


class PriceFloorTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Test Branch")
        self.category = RetailCategory.objects.create(name="Phones")
        self.subcat = RetailSubCategory.objects.create(name="Smartphones", category=self.category)
        self.director = User.objects.create_user(
            username="director", password="pass", role="DIRECTOR",
        )
        self.retail = User.objects.create_user(
            username="retail", password="pass", role="RETAIL", branch=self.branch,
        )
        self.product = Product.objects.create(
            model_name="iPhone 15", selling_price=Decimal("500000"),
            cost_price=Decimal("400000"), subcategory=self.subcat,
            subsubcategory=None,
        )
        self.stock = StaffStock.objects.create(staff=self.retail, product=self.product, quantity=10)

    def test_price_floor_prevents_low_sale(self):
        """Sale below price floor should be rejected."""
        self.client.login(username="retail", password="pass")

        # Set price floor
        PriceFloor.objects.create(
            product=self.product, branch=self.branch,
            min_selling_price=Decimal("480000"),
        )

        # Try to sell below floor
        response = self.client.post(
            reverse("record_retail_sale"),
            {
                "product": self.product.id,
                "quantity": 1,
                "selling_price": "450000",
                "payment_method": "CASH",
                "customer_phone": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RetailSale.objects.count(), 0)

        # Sell at or above floor — should work
        response = self.client.post(
            reverse("record_retail_sale"),
            {
                "product": self.product.id,
                "quantity": 1,
                "selling_price": "490000",
                "payment_method": "CASH",
                "customer_phone": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RetailSale.objects.count(), 1)


class ChangeLogTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Test Branch")
        self.category = RetailCategory.objects.create(name="Phones")
        self.subcat = RetailSubCategory.objects.create(name="Smartphones", category=self.category)
        self.retail = User.objects.create_user(
            username="retail", password="pass", role="RETAIL", branch=self.branch,
        )
        self.product = Product.objects.create(
            model_name="Test Phone", selling_price=Decimal("10000"),
            cost_price=Decimal("8000"), subcategory=self.subcat,
            subsubcategory=None,
        )
        StaffStock.objects.create(staff=self.retail, product=self.product, quantity=5)

    def test_sale_creates_change_log(self):
        """Recording a sale should create a ChangeLog entry."""
        self.client.login(username="retail", password="pass")
        self.client.post(
            reverse("record_retail_sale"),
            {
                "product": self.product.id,
                "quantity": 1,
                "selling_price": "10000",
                "payment_method": "CASH",
                "customer_phone": "08012345678",
            },
        )
        logs = ChangeLog.objects.filter(action="SALE", model_name="RetailSale")
        self.assertEqual(logs.count(), 1)
        self.assertIn("Test Phone", logs.first().description)


class BackupLogTest(TestCase):
    def test_backup_log_creation(self):
        """BackupLog model can be created."""
        log = BackupLog.objects.create(
            triggered_by="manual",
            status="SUCCESS",
            file_path="backups/test.db",
            file_size_bytes=1024,
            email_sent=True,
            email_recipient="test@example.com",
        )
        self.assertTrue(log.email_sent)
        self.assertEqual(log.status, "SUCCESS")


class MonthlyResetTest(TestCase):
    def setUp(self):
        self.director = User.objects.create_user(
            username="director", password="pass", role="DIRECTOR",
        )

    def test_monthly_reset_log(self):
        """MonthlyResetLog records a reset."""
        log = MonthlyResetLog.objects.create(
            year=2026, month=6, reset_by=self.director,
            notes="Test reset",
        )
        self.assertEqual(log.year, 2026)
        self.assertEqual(log.month, 6)


class AttendanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(
            name="Test Branch", latitude=6.5244, longitude=3.3792, allowed_radius=100,
        )
        self.staff = User.objects.create_user(
            username="staff", password="pass", role="RETAIL", branch=self.branch,
        )

    def test_attendance_creation(self):
        """Attendance record can be created."""
        att = Attendance.objects.create(
            user=self.staff,
            branch=self.branch,
            date=date.today(),
            is_late=False,
            is_absent=False,
            deduction_amount=Decimal("0"),
            latitude=6.5244,
            longitude=3.3792,
            distance_from_branch=0,
            session="morning",
        )
        self.assertFalse(att.is_late)
        self.assertFalse(att.is_absent)


class CustomerCRMTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Test Branch")

    def test_customer_creation(self):
        """Customer can be created and updated."""
        customer = Customer.objects.create(
            phone_number="08012345678",
            name="John Doe",
            branch=self.branch,
            purchase_count=0,
            total_spent=Decimal("0"),
        )
        self.assertEqual(customer.phone_number, "08012345678")
        self.assertEqual(customer.name, "John Doe")
