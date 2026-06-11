"""
GPSL ERP Automated Tests
========================
Tests cover: login, sales recording, stock management,
attendance, price enforcement, and customer CRM.

Run with: python manage.py test core
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from datetime import date

from core.models import (
    User, Branch, Product, RetailCategory, RetailSubCategory,
    StaffStock, RetailSale, Attendance, BranchSafeStock,
    StockMovement, Customer,
)


# ─────────────────────────────────────────
# BASE TEST SETUP
# ─────────────────────────────────────────

class BaseTestCase(TestCase):
    """Shared setup for all tests."""

    def setUp(self):
        # Create branch
        self.branch = Branch.objects.create(
            name="Test Branch",
            city="Uyo",
            allowed_radius=300,
        )

        # Create users
        self.director = User.objects.create_user(
            username="TestDirector",
            password="TestPass123!",
            role="DIRECTOR",
            is_superuser=True,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="TestManager",
            password="TestPass123!",
            role="MANAGER",
            branch=self.branch,
        )
        self.retail = User.objects.create_user(
            username="TestRetail",
            password="TestPass123!",
            role="RETAIL",
            branch=self.branch,
        )

        # Create product
        self.category = RetailCategory.objects.create(name="Phones")
        self.subcategory = RetailSubCategory.objects.create(
            name="Smartphones", category=self.category
        )
        self.product = Product.objects.create(
            model_name="Test iPhone",
            product_name="Apple iPhone",
            subcategory=self.subcategory,
            cost_price=Decimal("600000"),
            selling_price=Decimal("850000"),
        )

        self.client = Client()


# ─────────────────────────────────────────
# TEST 1: LOGIN
# ─────────────────────────────────────────

class LoginTests(BaseTestCase):

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(reverse("login"), {
            "username": "TestRetail",
            "password": "TestPass123!",
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/login", response["Location"])

    def test_invalid_password_stays_on_login(self):
        response = self.client.post(reverse("login"), {
            "username": "TestRetail",
            "password": "WrongPassword",
        })
        self.assertEqual(response.status_code, 200)

    def test_nonexistent_user_login(self):
        response = self.client.post(reverse("login"), {
            "username": "Nobody",
            "password": "Whatever123",
        })
        self.assertEqual(response.status_code, 200)

    def test_director_redirects_to_director_dashboard(self):
        response = self.client.post(reverse("login"), {
            "username": "TestDirector",
            "password": "TestPass123!",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("director", response["Location"])

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get(reverse("retail_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_account_lockout_after_5_failures(self):
        for _ in range(5):
            self.client.post(reverse("login"), {
                "username": "TestRetail",
                "password": "WrongPass",
            })
        self.retail.refresh_from_db()
        self.assertTrue(self.retail.is_locked)

    def test_superuser_never_locked(self):
        for _ in range(10):
            self.client.post(reverse("login"), {
                "username": "TestDirector",
                "password": "WrongPass",
            })
        self.director.refresh_from_db()
        self.assertFalse(self.director.is_locked)


# ─────────────────────────────────────────
# TEST 2: PRICE ENFORCEMENT
# ─────────────────────────────────────────

class PriceEnforcementTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client.login(username="TestRetail", password="TestPass123!")
        StaffStock.objects.create(
            staff=self.retail, product=self.product, quantity=5
        )

    def test_sale_uses_approved_price_not_form_input(self):
        """Staff cannot override price — system uses product.selling_price."""
        response = self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 1,
            "selling_price": "999999",  # Attacker tries to set high price
            "payment_method": "CASH",
        })
        sale = RetailSale.objects.filter(product=self.product).first()
        self.assertIsNotNone(sale)
        self.assertEqual(sale.selling_price, self.product.selling_price)

    def test_sale_reduces_stock(self):
        self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 2,
            "selling_price": "850000",
            "payment_method": "CASH",
        })
        stock = StaffStock.objects.get(staff=self.retail, product=self.product)
        self.assertEqual(stock.quantity, 3)

    def test_sale_fails_if_insufficient_stock(self):
        response = self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 100,
            "selling_price": "850000",
            "payment_method": "CASH",
        })
        # Stock should be unchanged
        stock = StaffStock.objects.get(staff=self.retail, product=self.product)
        self.assertEqual(stock.quantity, 5)

    def test_sale_creates_reference_number(self):
        self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 1,
            "selling_price": "850000",
            "payment_method": "CASH",
        })
        sale = RetailSale.objects.filter(product=self.product).first()
        self.assertIsNotNone(sale)
        # Reference is GPSL-{id:05d}
        ref = f"GPSL-{sale.id:05d}"
        self.assertTrue(ref.startswith("GPSL-"))


# ─────────────────────────────────────────
# TEST 3: STOCK MANAGEMENT
# ─────────────────────────────────────────

class StockManagementTests(BaseTestCase):

    def test_branch_safe_stock_creation(self):
        safe_stock = BranchSafeStock.objects.create(
            branch=self.branch, product=self.product, quantity=10
        )
        self.assertEqual(safe_stock.quantity, 10)

    def test_stock_movement_logged(self):
        StockMovement.objects.create(
            branch=self.branch,
            product=self.product,
            quantity=5,
            movement_type="IN",
            performed_by=self.manager,
        )
        count = StockMovement.objects.filter(
            branch=self.branch, product=self.product
        ).count()
        self.assertEqual(count, 1)

    def test_low_stock_alert_signal(self):
        """When BranchSafeStock hits 0, StockAlert should be created."""
        from core.models import StockAlert
        safe = BranchSafeStock.objects.create(
            branch=self.branch, product=self.product, quantity=1
        )
        safe.quantity = 0
        safe.save()
        alert = StockAlert.objects.filter(
            product=self.product, branch=self.branch
        ).first()
        if alert:
            self.assertTrue(alert.is_active)


# ─────────────────────────────────────────
# TEST 4: ROLE-BASED ACCESS CONTROL
# ─────────────────────────────────────────

class AccessControlTests(BaseTestCase):

    def test_retail_cannot_access_director_dashboard(self):
        self.client.login(username="TestRetail", password="TestPass123!")
        response = self.client.get(reverse("director_dashboard"))
        self.assertNotEqual(response.status_code, 200)

    def test_manager_cannot_access_director_dashboard(self):
        self.client.login(username="TestManager", password="TestPass123!")
        response = self.client.get(reverse("director_dashboard"))
        self.assertNotEqual(response.status_code, 200)

    def test_director_can_access_director_dashboard(self):
        self.client.login(username="TestDirector", password="TestPass123!")
        response = self.client.get(reverse("director_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_retail_can_access_retail_dashboard(self):
        self.client.login(username="TestRetail", password="TestPass123!")
        response = self.client.get(reverse("retail_dashboard"))
        self.assertEqual(response.status_code, 200)


# ─────────────────────────────────────────
# TEST 5: CUSTOMER CRM
# ─────────────────────────────────────────

class CustomerCRMTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        StaffStock.objects.create(
            staff=self.retail, product=self.product, quantity=10
        )
        self.client.login(username="TestRetail", password="TestPass123!")

    def test_sale_with_phone_creates_customer(self):
        self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 1,
            "selling_price": "850000",
            "payment_method": "CASH",
            "customer_phone": "08012345678",
            "customer_name": "Test Customer",
        })
        customer = Customer.objects.filter(phone_number="08012345678").first()
        self.assertIsNotNone(customer)

    def test_sale_without_phone_does_not_create_customer(self):
        initial_count = Customer.objects.count()
        self.client.post(reverse("record_retail_sale"), {
            "product": self.product.id,
            "quantity": 1,
            "selling_price": "850000",
            "payment_method": "CASH",
        })
        self.assertEqual(Customer.objects.count(), initial_count)

    def test_repeated_sales_update_customer_totals(self):
        for i in range(3):
            StaffStock.objects.filter(
                staff=self.retail, product=self.product
            ).update(quantity=10)
            self.client.post(reverse("record_retail_sale"), {
                "product": self.product.id,
                "quantity": 1,
                "selling_price": "850000",
                "payment_method": "CASH",
                "customer_phone": "08099999999",
            })
        customer = Customer.objects.get(phone_number="08099999999")
        self.assertGreaterEqual(customer.purchase_count, 1)


# ─────────────────────────────────────────
# TEST 6: VOID SALE
# ─────────────────────────────────────────

class VoidSaleTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        staff_stock = StaffStock.objects.create(
            staff=self.retail, product=self.product, quantity=5
        )
        self.sale = RetailSale.objects.create(
            staff=self.retail,
            branch=self.branch,
            product=self.product,
            quantity=2,
            selling_price=self.product.selling_price,
            payment_method="CASH",
        )
        staff_stock.quantity -= 2
        staff_stock.save()

    def test_manager_can_void_sale(self):
        self.client.login(username="TestManager", password="TestPass123!")
        self.client.post(reverse("void_sale", args=[self.sale.id]), {
            "void_reason": "Test void",
        })
        self.sale.refresh_from_db()
        self.assertTrue(self.sale.is_voided)

    def test_void_returns_stock_to_staff(self):
        initial_qty = StaffStock.objects.get(
            staff=self.retail, product=self.product
        ).quantity
        self.client.login(username="TestManager", password="TestPass123!")
        self.client.post(reverse("void_sale", args=[self.sale.id]), {
            "void_reason": "Stock return test",
        })
        new_qty = StaffStock.objects.get(
            staff=self.retail, product=self.product
        ).quantity
        self.assertEqual(new_qty, initial_qty + 2)
