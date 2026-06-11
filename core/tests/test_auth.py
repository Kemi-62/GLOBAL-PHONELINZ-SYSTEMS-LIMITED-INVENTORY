import os
import tempfile
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Branch, Attendance, CheckInOutLog

User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), MEDIA_URL="/media/")
class AuthTest(TestCase):
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
        self.client = Client()

    # ── Login ──
    def test_login_page_loads(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Login")

    def test_login_success(self):
        resp = self.client.post(reverse("login"), {"username": "testmanager", "password": "testpass123"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/manager"))

    def test_login_redirect_when_authenticated(self):
        self.client.login(username="testmanager", password="testpass123")
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 302)

    def test_login_invalid(self):
        resp = self.client.post(reverse("login"), {"username": "testmanager", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid")

    def test_logout(self):
        self.client.login(username="testmanager", password="testpass123")
        resp = self.client.get(reverse("logout"))
        self.assertEqual(resp.status_code, 302)

    def test_role_redirects(self):
        for user, expected in [
            ("testdirector", "/director"),
            ("testmanager", "/manager"),
            ("testretail", "/retail"),
        ]:
            self.client.login(username=user, password="testpass123")
            resp = self.client.get(reverse("login"))
            self.assertTrue(resp.url.startswith(expected), f"{user} should redirect to {expected}")
            self.client.logout()

    # ── Dashboard access ──
    def test_manager_dashboard_requires_login(self):
        resp = self.client.get(reverse("manager_dashboard"))
        self.assertEqual(resp.status_code, 302)

    def test_manager_dashboard_loads(self):
        self.client.login(username="testmanager", password="testpass123")
        resp = self.client.get(reverse("manager_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manager")

    def test_director_dashboard_loads(self):
        self.client.login(username="testdirector", password="testpass123")
        resp = self.client.get(reverse("director_dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_retail_dashboard_loads(self):
        self.client.login(username="testretail", password="testpass123")
        resp = self.client.get(reverse("retail_dashboard"))
        self.assertEqual(resp.status_code, 200)

    # ── Attendance check-in ──
    def test_check_in_requires_login(self):
        resp = self.client.post(reverse("check_in"), {"latitude": "5.0", "longitude": "7.0"})
        self.assertEqual(resp.status_code, 302)

    def test_check_in_saves_record(self):
        self.client.login(username="testretail", password="testpass123")
        self.branch.latitude = 5.0
        self.branch.longitude = 7.0
        self.branch.save()
        Attendance.objects.create(
            user=self.retail, branch=self.branch, session="morning",
            latitude=5.0, longitude=7.0, distance_from_branch=0,
            date="2026-06-11", check_in_time="2026-06-11 08:00:00"
        )
        self.assertTrue(Attendance.objects.filter(user=self.retail).exists())

    def test_check_out(self):
        self.client.login(username="testretail", password="testpass123")
        self.branch.latitude = 5.0
        self.branch.longitude = 7.0
        self.branch.save()
        # create attendance first
        Attendance.objects.create(
            user=self.retail, branch=self.branch, date="2026-06-11", session="morning",
            latitude=5.0, longitude=7.0, distance_from_branch=0,
            check_in_time="2026-06-11 08:00:00"
        )
        resp = self.client.post(
            reverse("check_out"),
            {"latitude": "5.0", "longitude": "7.0"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Check-out successful")

    def test_attendance_history(self):
        self.client.login(username="testretail", password="testpass123")
        Attendance.objects.create(
            user=self.retail, branch=self.branch, date="2026-06-11", session="morning",
            latitude=5.0, longitude=7.0, distance_from_branch=0
        )
        resp = self.client.get(reverse("attendance_history"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Attendance History")

    # ── Staff movement ──
    def test_staff_checkout(self):
        self.client.login(username="testmanager", password="testpass123")
        resp = self.client.post(reverse("staff_checkout", args=[self.retail.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CheckInOutLog.objects.filter(staff=self.retail).exists())

    def test_staff_checkin(self):
        self.client.login(username="testmanager", password="testpass123")
        log = CheckInOutLog.objects.create(staff=self.retail, branch=self.branch, check_in_time="2026-06-11 09:00:00")
        resp = self.client.post(reverse("staff_checkin", args=[self.retail.id]))
        self.assertEqual(resp.status_code, 302)
