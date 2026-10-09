"""Verification-only tests for the stock approval workflow (not delivered)."""
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import stock_approvals as sa
from core.models import (
    Branch, BranchSafeStock, DirectorSafeStock, Notification, Product, RetailCategory,
    RetailSubCategory, StaffStock, StockApprovalEvent, StockApprovalRequest as R,
    StockMovement, StockTransfer, User,
)
from core.stock_approvals import StockError


def qty(model, **kw):
    return sum(r.quantity for r in model.objects.filter(**kw))


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False)
class Base(TestCase):
    def setUp(self):
        self.b1 = Branch.objects.create(name="Uyo Main")
        self.b2 = Branch.objects.create(name="Eket")
        mk = lambda n, role, b=None: User.objects.create_user(n, password="x", role=role, branch=b)
        self.director = mk("director", "DIRECTOR")
        self.mgr1 = mk("mgr1", "MANAGER", self.b1)
        self.mgr2 = mk("mgr2", "MANAGER", self.b2)
        self.r1 = mk("r1", "RETAIL", self.b1)
        self.r2 = mk("r2", "RETAIL", self.b1)
        self.r3 = mk("r3", "RETAIL", self.b2)
        self.tel = mk("tel1", "TELECOM", self.b1)
        cat = RetailCategory.objects.create(name="Phones")
        self.sub = RetailSubCategory.objects.create(category=cat, name="Android")
        self.p = Product.objects.create(subcategory=self.sub, model_name="Tecno Spark", color="Blue", cost_price=1000, selling_price=1500)
        self.p2 = Product.objects.create(subcategory=self.sub, model_name="Itel A60", cost_price=500, selling_price=800)
        DirectorSafeStock.objects.create(product=self.p, quantity=6)
        DirectorSafeStock.objects.create(product=self.p, quantity=4)      # one row per addition, like production

    def D(self, p=None):
        return sa.available("DIRECTOR", p or self.p)

    def B(self, branch=None, p=None):
        return sa.available("BRANCH", p or self.p, branch=branch or self.b1)

    def S(self, staff, p=None):
        return sa.available("STAFF", p or self.p, staff=staff)

    def give_branch(self, n, branch=None, p=None):
        sa.credit("BRANCH", p or self.p, n, branch=branch or self.b1)

    def give_staff(self, staff, n, p=None):
        sa.credit("STAFF", p or self.p, n, staff=staff)

    def notes(self, user, text=""):
        return Notification.objects.filter(recipient=user, title__icontains=text)


class NormalChain(Base):
    def test_director_to_branch_in_transit_accept(self):
        req = sa.submit_move(self.director, self.p, 7, "DIRECTOR", "BRANCH", to_branch=self.b1)
        self.assertEqual((self.D(), self.B()), (3, 0))                     # taken across BOTH rows, in transit
        self.assertEqual((req.status, req.approval_stage), ("PENDING", "MANAGER"))
        self.assertTrue(req.in_transit)
        self.assertTrue(self.notes(self.mgr1, "approval").exists())
        self.assertFalse(self.notes(self.mgr2).exists())                   # other branch not bothered
        for nobody in (self.director, self.mgr2, self.r1):
            self.assertFalse(sa.can_act(nobody, req))
            with self.assertRaises(StockError):
                sa.approve(req.id, nobody)
        self.assertEqual((self.D(), self.B()), (3, 0))
        sa.approve(req.id, self.mgr1)
        req.refresh_from_db()
        self.assertEqual((self.D(), self.B()), (3, 7))
        self.assertEqual((req.status, req.approval_stage, req.approved_by), ("APPROVED", "NONE", self.mgr1))
        self.assertTrue(StockTransfer.objects.filter(transfer_type="DIRECTOR_TO_BRANCH", quantity=7, to_branch=self.b1).exists())
        self.assertTrue(StockMovement.objects.filter(branch=self.b1, movement_type="IN", quantity=7).exists())
        with self.assertRaises(StockError):                                # no double approval
            sa.approve(req.id, self.mgr1)
        self.assertEqual(self.B(), 7)

    def test_rejection_needs_reason_returns_stock_and_tells_requester(self):
        req = sa.submit_move(self.director, self.p, 7, "DIRECTOR", "BRANCH", to_branch=self.b1)
        for bad in ("", "  ", "x"):
            with self.assertRaises(StockError):
                sa.reject(req.id, self.mgr1, bad)
        self.assertEqual((self.D(), req.status), (3, "PENDING"))
        sa.reject(req.id, self.mgr1, "Wrong item delivered")
        req.refresh_from_db()
        self.assertEqual((self.D(), self.B(), req.status), (10, 0, "REJECTED"))
        self.assertEqual(req.rejection_reason, "Wrong item delivered")
        self.assertIsNotNone(req.rejected_at)
        n = self.notes(self.director, "rejected").first()
        self.assertIn("Wrong item delivered", n.message)
        self.assertFalse(StockTransfer.objects.exists())
        self.assertTrue(R.objects.filter(pk=req.pk).exists())              # kept for audit

    def test_release_to_staff_needs_staff_to_accept(self):
        self.give_branch(5)
        req = sa.submit_move(self.mgr1, self.p, 3, "BRANCH", "STAFF", from_branch=self.b1, to_staff=self.r1)
        self.assertEqual((self.B(), self.S(self.r1), req.approval_stage), (2, 0, "STAFF"))
        self.assertTrue(self.notes(self.r1, "accept").exists())
        for nobody in (self.mgr1, self.r2, self.mgr2):
            self.assertFalse(sa.can_act(nobody, req))
        sa.approve(req.id, self.r1)
        self.assertEqual((self.B(), self.S(self.r1)), (2, 3))
        self.assertTrue(StockMovement.objects.filter(movement_type="OUT", quantity=3, branch=self.b1).exists())

    def test_staff_reject_returns_to_branch_safe(self):
        self.give_branch(5)
        req = sa.submit_move(self.mgr1, self.p, 3, "BRANCH", "STAFF", from_branch=self.b1, to_staff=self.r1)
        sa.reject(req.id, self.r1, "I did not receive these")
        self.assertEqual((self.B(), self.S(self.r1)), (5, 0))

    def test_director_can_act_for_absent_staff(self):
        self.give_branch(5)
        req = sa.submit_move(self.mgr1, self.p, 2, "BRANCH", "STAFF", from_branch=self.b1, to_staff=self.r1)
        sa.approve(req.id, self.director)
        self.assertEqual(self.S(self.r1), 2)
        self.assertIn("acted for", req.events.last().detail)

    def test_insufficient_stock_and_row_total(self):
        with self.assertRaises(StockError) as ctx:
            sa.submit_move(self.director, self.p, 11, "DIRECTOR", "BRANCH", to_branch=self.b1)
        self.assertIn("Only 10", str(ctx.exception))
        self.assertEqual((R.objects.count(), self.D()), (0, 10))
        sa.submit_move(self.director, self.p, 8, "DIRECTOR", "BRANCH", to_branch=self.b1)   # 8 > first row (6)
        self.assertEqual(self.D(), 2)

    def test_auto_complete_when_requester_owns_destination(self):
        self.give_staff(self.r1, 5)
        req = sa.submit_move(self.mgr1, self.p, 2, "STAFF", "BRANCH", from_staff=self.r1, to_branch=self.b1)
        self.assertEqual((req.status, self.S(self.r1), self.B()), ("APPROVED", 3, 2))
        self.assertEqual(req.events.last().action, "AUTO_COMPLETED")
        self.give_branch(4)
        req2 = sa.submit_move(self.director, self.p, 4, "BRANCH", "DIRECTOR", from_branch=self.b1)
        self.assertEqual((req2.status, self.D()), ("APPROVED", 14))

    def test_manager_limits(self):
        self.give_staff(self.r3, 5)
        self.give_branch(5, self.b2)
        with self.assertRaises(StockError):
            sa.submit_move(self.mgr1, self.p, 1, "STAFF", "BRANCH", from_staff=self.r3, to_branch=self.b1)   # other branch's staff
        with self.assertRaises(StockError):
            sa.submit_move(self.mgr1, self.p, 1, "BRANCH", "BRANCH", from_branch=self.b2, to_branch=self.b1)
        with self.assertRaises(StockError):
            sa.submit_move(self.mgr1, self.p, 1, "DIRECTOR", "BRANCH", to_branch=self.b1)
        with self.assertRaises(StockError):
            sa.submit_move(self.r1, self.p, 1, "STAFF", "BRANCH", from_staff=self.r1, to_branch=self.b1)
        self.assertEqual((self.D(), self.S(self.r3), self.B(self.b2)), (10, 5, 5))

    def test_branch_to_branch_is_accepted_by_destination_manager(self):
        self.give_branch(5)
        req = sa.submit_move(self.mgr1, self.p, 3, "BRANCH", "BRANCH", from_branch=self.b1, to_branch=self.b2)
        self.assertEqual(req.approval_stage, "MANAGER")
        self.assertFalse(sa.can_act(self.mgr1, req))
        sa.approve(req.id, self.mgr2)
        self.assertEqual((self.B(self.b1), self.B(self.b2)), (2, 3))

    def test_staff_must_belong_to_the_branch(self):
        self.give_branch(5)
        with self.assertRaises(StockError):
            sa.submit_move(self.mgr1, self.p, 1, "BRANCH", "STAFF", from_branch=self.b1, to_staff=self.r3)
        with self.assertRaises(StockError):
            sa.submit_move(self.director, self.p, 1, "DIRECTOR", "STAFF", to_staff=self.mgr1)


class ManualEntries(Base):
    def test_edge_case_1_full_chain(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF", source_type="MANUAL_DIRECTOR", note="Director gave me these")
        self.assertEqual((self.S(self.r1), req.approval_stage, req.status), (0, "MANAGER", "PENDING"))
        self.assertTrue(req.is_exception)
        self.assertTrue(self.notes(self.mgr1, "approval").exists())
        for nobody in (self.r1, self.mgr2, self.r2):
            self.assertFalse(sa.can_act(nobody, req))
        sa.approve(req.id, self.mgr1)
        req.refresh_from_db()
        self.assertEqual(self.S(self.r1), 5)                               # real the moment the manager approves
        self.assertEqual((req.status, req.approval_stage), ("PENDING", "DIRECTOR"))
        self.assertTrue(StockMovement.objects.filter(movement_type="OUT", quantity=5, branch=self.b1).exists())
        self.assertTrue(self.notes(self.director, "confirmation").exists())
        self.assertFalse(sa.can_edit(self.r1, req))                        # now locked
        with self.assertRaises(StockError):
            sa.edit(req.id, self.r1, quantity=1)
        with self.assertRaises(StockError):
            sa.cancel(req.id, self.r1)
        sa.approve(req.id, self.director)
        req.refresh_from_db()
        self.assertEqual((req.status, req.approval_stage, self.S(self.r1)), ("APPROVED", "NONE", 5))

    def test_late_director_rejection_reverses_and_flags_shortfall(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF", source_type="MANUAL_DIRECTOR")
        sa.approve(req.id, self.mgr1)
        sa.debit("STAFF", self.p, 2, staff=self.r1)                        # 2 already sold
        sa.reject(req.id, self.director, "I never handed these over")
        req.refresh_from_db()
        self.assertEqual((req.status, req.reversed_quantity, req.shortfall_quantity, self.S(self.r1)), ("REJECTED", 3, 2, 0))
        self.assertFalse(req.stock_applied)
        self.assertIn("SHORTFALL", req.events.last().detail)
        self.assertIn("never handed", self.notes(self.r1, "rejected").first().message)
        self.assertTrue(self.notes(self.director, "shortfall").exists())
        self.assertTrue(self.notes(self.mgr1, "shortfall").exists())

    def test_late_rejection_when_everything_sold_and_when_staff_has_more(self):
        req = sa.submit_entry(self.r1, self.p, 4, "STAFF", source_type="MANUAL_DIRECTOR")
        sa.approve(req.id, self.mgr1)
        sa.debit("STAFF", self.p, 4, staff=self.r1)
        sa.reject(req.id, self.director, "not mine to approve")
        req.refresh_from_db()
        self.assertEqual((req.reversed_quantity, req.shortfall_quantity), (0, 4))
        req2 = sa.submit_entry(self.r2, self.p, 4, "STAFF", source_type="MANUAL_DIRECTOR")
        self.give_staff(self.r2, 3)                                         # 3 from elsewhere
        sa.approve(req2.id, self.mgr1)                                      # now 7
        sa.reject(req2.id, self.director, "not mine to approve")
        req2.refresh_from_db()
        self.assertEqual((req2.reversed_quantity, req2.shortfall_quantity, self.S(self.r2)), (4, 0, 3))
        self.assertTrue(StockApprovalEvent.objects.filter(request=req2, action="REJECTED").exists())

    def test_manager_rejection_never_touches_stock(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF", source_type="MANUAL_DIRECTOR")
        with self.assertRaises(StockError):
            sa.reject(req.id, self.mgr1, "")
        sa.reject(req.id, self.mgr1, "Count does not match the delivery note")
        req.refresh_from_db()
        self.assertEqual((req.status, self.S(self.r1), req.reversed_quantity, req.shortfall_quantity), ("REJECTED", 0, 0, 0))
        self.assertIn("delivery note", self.notes(self.r1, "rejected").first().message)
        self.assertFalse(sa.can_act(self.director, req))                   # finished

    def test_staff_entry_not_from_director_needs_manager_only(self):
        req = sa.submit_entry(self.r1, self.p, 3, "STAFF", source_type="MANUAL_OTHER")
        sa.approve(req.id, self.mgr1)
        req.refresh_from_db()
        self.assertEqual((req.status, req.approval_stage, self.S(self.r1)), ("APPROVED", "NONE", 3))
        self.assertFalse(StockMovement.objects.filter(movement_type="OUT").exists())
        with self.assertRaises(StockError):
            sa.approve(req.id, self.mgr1)
        self.assertEqual(self.S(self.r1), 3)

    def test_edge_case_2_manager_entry_needs_director(self):
        req = sa.submit_entry(self.mgr1, self.p, 4, "BRANCH", source_type="MANUAL_DIRECTOR")  # cannot claim Director origin
        self.assertEqual((req.source_type, req.approval_stage, self.B()), ("MANUAL_OTHER", "DIRECTOR", 0))
        self.assertFalse(sa.can_act(self.mgr1, req))
        self.assertFalse(sa.can_act(self.mgr2, req))
        self.assertTrue(self.notes(self.director, "approval").exists())
        sa.approve(req.id, self.director)
        req.refresh_from_db()
        self.assertEqual((req.status, self.B()), ("APPROVED", 4))
        self.assertTrue(StockMovement.objects.filter(movement_type="IN", branch=self.b1, quantity=4).exists())
        req2 = sa.submit_entry(self.mgr1, self.p2, 6, "BRANCH")
        sa.reject(req2.id, self.director, "Not on any purchase order")
        self.assertEqual(self.B(p=self.p2), 0)
        self.assertEqual(R.objects.get(pk=req2.pk).status, "REJECTED")

    def test_who_may_submit_entries(self):
        with self.assertRaises(StockError):
            sa.submit_entry(self.r1, self.p, 3, "BRANCH")
        with self.assertRaises(StockError):
            sa.submit_entry(self.mgr1, self.p, 3, "STAFF")
        with self.assertRaises(StockError):
            sa.submit_entry(self.director, self.p, 3, "BRANCH")
        for bad in (0, -2, "abc", None):
            with self.assertRaises(StockError):
                sa.submit_entry(self.r1, self.p, bad, "STAFF")
        self.assertEqual(R.objects.count(), 0)

    def test_edit_and_cancel_lock(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF", note="5 phones")
        self.assertTrue(sa.can_edit(self.r1, req))
        for other in (self.r2, self.mgr1, self.director):
            self.assertFalse(sa.can_edit(other, req))
            with self.assertRaises(StockError):
                sa.edit(req.id, other, quantity=1)
            with self.assertRaises(StockError):
                sa.cancel(req.id, other)
        sa.edit(req.id, self.r1, quantity=3, note="only 3 phones")
        req.refresh_from_db()
        self.assertEqual((req.quantity, req.notes), (3, "only 3 phones"))
        detail = req.events.filter(action="EDITED").first().detail
        self.assertIn("Quantity 5 -> 3", detail)
        self.assertIn("'5 phones' -> 'only 3 phones'", detail)             # old value is never lost
        sa.cancel(req.id, self.r1)
        req.refresh_from_db()
        self.assertEqual(req.status, "CANCELLED")
        self.assertFalse(sa.can_act(self.mgr1, req))
        req2 = sa.submit_entry(self.r1, self.p, 2, "STAFF")
        sa.approve(req2.id, self.mgr1)
        with self.assertRaises(StockError):
            sa.edit(req2.id, self.r1, quantity=50)
        self.assertEqual(R.objects.get(pk=req2.pk).quantity, 2)

    def test_editing_or_cancelling_an_in_transit_move_keeps_stock_honest(self):
        req = sa.submit_move(self.director, self.p, 4, "DIRECTOR", "BRANCH", to_branch=self.b1)
        sa.edit(req.id, self.director, quantity=6)
        self.assertEqual(self.D(), 4)
        sa.edit(req.id, self.director, quantity=1)
        self.assertEqual(self.D(), 9)
        with self.assertRaises(StockError):
            sa.edit(req.id, self.director, quantity=999)
        self.assertEqual((self.D(), R.objects.get(pk=req.pk).quantity), (9, 1))
        sa.cancel(req.id, self.director)
        self.assertEqual((self.D(), self.B()), (10, 0))
        sa.approve  # nothing left to approve
        with self.assertRaises(StockError):
            sa.approve(req.id, self.mgr1)

    def test_self_recorded_reduction(self):
        self.give_staff(self.r1, 5)
        for bad in ("", "  ", "x"):
            with self.assertRaises(StockError):
                sa.record_reduction(self.r1, self.p, 2, bad)
        with self.assertRaises(StockError):
            sa.record_reduction(self.r1, self.p, 9, "damaged")
        self.assertEqual((self.S(self.r1), R.objects.count()), (5, 0))
        req = sa.record_reduction(self.r1, self.p, 2, "2 units damaged in transit")
        self.assertEqual((self.S(self.r1), req.kind, req.status, req.is_exception), (3, "ADJUST_DOWN", "APPROVED", True))
        self.assertIn("damaged", self.notes(self.mgr1, "reduced").first().message)
        self.assertFalse(sa.can_edit(self.r1, req))

    def test_batch_approve_and_reject(self):
        for i in range(3):
            sa.submit_entry(self.mgr1, self.p, i + 1, "BRANCH", batch_ref="BATCH1")
        sa.submit_entry(self.mgr1, self.p, 9, "BRANCH", batch_ref="BATCH2")
        done, failed = sa.approve_batch("BATCH1", self.director)
        self.assertEqual((done, failed, self.B()), (3, [], 6))
        self.assertEqual(R.objects.get(batch_ref="BATCH2").status, "PENDING")
        done, _ = sa.reject_batch("BATCH2", self.director, "Wrong file uploaded")
        self.assertEqual((done, self.B()), (1, 6))
        self.assertEqual(sa.approve_batch("BATCH1", self.mgr1), (0, []))     # nothing actionable for the wrong person

    def test_inboxes_are_scoped(self):
        a = sa.submit_entry(self.r1, self.p, 1, "STAFF")                    # manager 1
        b = sa.submit_entry(self.r3, self.p, 1, "STAFF")                    # manager 2
        c = sa.submit_entry(self.mgr1, self.p, 1, "BRANCH")                 # director
        self.give_branch(3)
        d = sa.submit_move(self.mgr1, self.p, 1, "BRANCH", "STAFF", from_branch=self.b1, to_staff=self.r2)   # r2
        self.assertEqual({r.id for r in sa.actionable_for(self.mgr1)}, {a.id})
        self.assertEqual({r.id for r in sa.actionable_for(self.mgr2)}, {b.id})
        self.assertEqual({r.id for r in sa.actionable_for(self.director)}, {c.id})
        self.assertEqual({r.id for r in sa.actionable_for(self.r2)}, {d.id})
        self.assertEqual(sa.actionable_for(self.r1).count(), 0)
        self.assertEqual({r.id for r in sa.oversight_for(self.director)}, {a.id, b.id, d.id})
        self.assertEqual((sa.pending_count(self.mgr1), sa.pending_count(self.director)), (1, 1))


class Screens(Base):
    def login(self, user):
        self.client.force_login(user)

    def msgs(self, resp):
        return [str(m) for m in resp.context["messages"]] if resp.context and "messages" in resp.context else []

    def test_stock_transfer_page_no_longer_fails_and_records_history(self):
        self.login(self.director)
        resp = self.client.post(reverse("stock_transfer"), {"transfer_type": "DIRECTOR_TO_BRANCH", "product": self.p.id,
                                "quantity": 4, "to_branch": self.b1.id, "notes": "restock"}, follow=True)
        text = " ".join(self.msgs(resp))
        self.assertNotIn("failed", text.lower())
        self.assertIn("on its way", text)
        self.assertEqual((self.D(), self.B()), (6, 0))
        req = R.objects.get()
        self.assertEqual((req.status, req.notes), ("PENDING", "restock"))
        page = self.client.get(reverse("stock_transfer"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context["pending_requests"]), 1)
        self.login(self.mgr1)
        self.client.post(reverse("stock_approval_approve", args=[req.id]))
        self.assertEqual((self.D(), self.B()), (6, 4))
        self.login(self.director)
        hist = self.client.get(reverse("stock_transfer_history"))
        self.assertEqual(hist.status_code, 200)
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_stock_transfer_errors_change_nothing(self):
        self.login(self.director)
        resp = self.client.post(reverse("stock_transfer"), {"transfer_type": "DIRECTOR_TO_BRANCH", "product": self.p.id,
                                "quantity": 99, "to_branch": self.b1.id}, follow=True)
        self.assertIn("Only 10", " ".join(self.msgs(resp)))
        self.assertEqual((self.D(), R.objects.count()), (10, 0))
        self.login(self.mgr1)
        resp = self.client.post(reverse("stock_transfer"), {"transfer_type": "DIRECTOR_TO_BRANCH", "product": self.p.id,
                                "quantity": 1, "to_branch": self.b1.id}, follow=True)
        self.assertIn("Only the Director", " ".join(self.msgs(resp)))
        self.assertEqual(self.D(), 10)

    def test_stock_transfer_staff_return_by_manager_completes_at_once(self):
        self.give_staff(self.r1, 5)
        self.login(self.mgr1)
        resp = self.client.post(reverse("stock_transfer"), {"transfer_type": "STAFF_TO_BRANCH", "product": self.p.id,
                                "quantity": 2, "to_staff": self.r1.id, "to_branch": self.b1.id}, follow=True)
        self.assertIn("Transfer complete", " ".join(self.msgs(resp)))
        self.assertEqual((self.S(self.r1), self.B()), (3, 2))

    def test_manager_add_stock_view(self):
        self.login(self.mgr1)
        resp = self.client.post(reverse("add_stock_to_safe"), {"product": self.p.id, "quantity": 5, "notes": "bought locally"}, follow=True)
        self.assertIn("Director approval", " ".join(self.msgs(resp)))
        self.assertEqual(self.B(), 0)
        req = R.objects.get()
        self.assertEqual((req.kind, req.approval_stage, req.notes), ("ENTRY", "DIRECTOR", "bought locally"))
        self.client.post(reverse("add_stock_to_safe"), {"product": self.p.id, "quantity": 0})
        self.assertEqual(R.objects.count(), 1)
        self.login(self.director)
        self.client.post(reverse("stock_approval_approve", args=[req.id]))
        self.assertEqual(self.B(), 5)

    def test_manager_new_product_creates_product_but_no_stock(self):
        self.login(self.mgr1)
        before = Product.objects.count()
        self.client.post(reverse("add_stock_to_safe"), {
            "is_new_product": "true", "category": self.sub.category.id, "new_subcategory": "Android",
            "model_name": "Infinix Hot", "cost_price": "900", "selling_price": "1300", "quantity": 3})
        self.assertEqual(Product.objects.count(), before + 1)
        self.assertEqual(Product.objects.get(model_name="Infinix Hot").cost_price, 900)
        self.assertEqual(self.B(p=Product.objects.get(model_name="Infinix Hot")), 0)
        self.assertEqual(R.objects.get().quantity, 3)

    def test_manager_release_view_and_staff_accepts(self):
        self.give_branch(5)
        self.login(self.mgr1)
        self.client.post(reverse("release_stock"), {"product": self.p.id, "staff": self.r1.id, "quantity": 3})
        req = R.objects.get()
        self.assertEqual((self.B(), self.S(self.r1), req.approval_stage), (2, 0, "STAFF"))
        self.client.post(reverse("release_stock"), {"product": self.p.id, "staff": self.r1.id, "quantity": 50})
        self.assertEqual(R.objects.count(), 1)
        self.login(self.r1)
        self.client.post(reverse("stock_approval_approve", args=[req.id]))
        self.assertEqual(self.S(self.r1), 3)

    def test_staff_create_product_view(self):
        self.login(self.r1)
        for model in ("Phone A", "Phone B"):                                # two with no IMEI must not clash
            self.client.post(reverse("staff_create_product"), {
                "category": self.sub.category.id, "new_subcategory": "Android", "model_name": model,
                "selling_price": "1000", "quantity": 2, "received_from": "DIRECTOR", "imei": ""})
        self.assertEqual(Product.objects.filter(model_name__in=["Phone A", "Phone B"]).count(), 2)
        self.assertEqual(StaffStock.objects.filter(staff=self.r1).count(), 0)
        reqs = R.objects.all()
        self.assertEqual(reqs.count(), 2)
        self.assertTrue(all(r.source_type == "MANUAL_DIRECTOR" and r.approval_stage == "MANAGER" for r in reqs))
        self.client.post(reverse("staff_create_product"), {
            "category": self.sub.category.id, "new_subcategory": "Android", "model_name": "Phone C",
            "selling_price": "1000", "quantity": 1})
        self.assertEqual(R.objects.get(product__model_name="Phone C").source_type, "MANUAL_OTHER")
        self.login(self.tel)                                                # telecom staff cannot
        self.client.post(reverse("staff_create_product"), {"category": self.sub.category.id, "new_subcategory": "x", "model_name": "Z", "quantity": 1})
        self.assertFalse(Product.objects.filter(model_name="Z").exists())

    def test_staff_quantity_edit_flow(self):
        self.give_staff(self.r1, 5)
        row = StaffStock.objects.get(staff=self.r1, product=self.p)
        url = reverse("edit_staff_stock_quantity", args=[row.id])
        self.login(self.r1)
        resp = self.client.get(url, {"quantity": 8})                        # GET only shows a form
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["increase"])
        self.assertEqual((self.S(self.r1), R.objects.count()), (5, 0))
        resp = self.client.post(url, {"quantity": 8, "reason": "3 more received", "received_from": "DIRECTOR"}, follow=True)
        self.assertEqual((self.S(self.r1), R.objects.count()), (5, 1))
        req = R.objects.get()
        self.assertEqual((req.quantity, req.source_type, req.kind), (3, "MANUAL_DIRECTOR", "ENTRY"))
        resp = self.client.post(url, {"quantity": 2, "reason": ""})        # decrease without reason
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((self.S(self.r1), R.objects.count()), (5, 1))
        self.client.post(url, {"quantity": 2, "reason": "returned 3 to manager"})
        self.assertEqual(self.S(self.r1), 2)
        self.assertEqual(R.objects.filter(kind="ADJUST_DOWN").count(), 1)
        self.login(self.r2)                                                 # someone else's stock
        self.assertEqual(self.client.get(url, {"quantity": 1}).status_code, 404)
        self.login(self.tel)
        self.assertEqual(self.client.get(url, {"quantity": 1}).status_code, 403)

    def test_director_release_view(self):
        self.login(self.director)
        url = reverse("director_release_stock")
        self.client.post(url, {"product_id": self.p.id, "quantity": 3, "release_type": "branch_safe", "branch_id": self.b1.id})
        self.client.post(url, {"product_id": self.p.id, "quantity": 2, "release_type": "staff", "staff_id": self.r3.id})
        self.assertEqual((self.D(), R.objects.filter(status="PENDING").count()), (5, 2))
        self.assertEqual(R.objects.get(dest_tier="STAFF").to_branch, self.b2)
        self.client.post(url, {"product_id": self.p.id, "quantity": 5, "release_type": "sale", "branch_id": self.b1.id})
        self.assertEqual(self.D(), 0)                                       # 5 taken across rows
        self.assertFalse(DirectorSafeStock.objects.filter(product=self.p).exists())
        resp = self.client.post(url, {"product_id": self.p.id, "quantity": 1, "release_type": "sale"}, follow=True)
        self.assertIn("not found", " ".join(self.msgs(resp)))
        self.assertEqual(self.D(), 0)

    def test_inbox_actions_and_permissions(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("stock_approvals")).status_code, 302)
        for user in (self.director, self.mgr1, self.mgr2, self.r1, self.tel):
            self.login(user)
            resp = self.client.get(reverse("stock_approvals"))
            self.assertEqual(resp.status_code, 200, user.username)
            self.assertContains(resp, "Pending Approvals")
        self.login(self.mgr1)
        resp = self.client.get(reverse("stock_approvals"))
        self.assertContains(resp, "Waiting for you (1)")
        self.assertContains(resp, "Tecno Spark")
        self.assertContains(resp, "Reason for rejecting")
        self.assertContains(resp, "Stock Approvals")                        # sidebar block present
        self.assertEqual(self.client.get(reverse("stock_approval_approve", args=[req.id])).status_code, 405)
        self.login(self.mgr2)                                               # wrong branch
        resp = self.client.post(reverse("stock_approval_approve", args=[req.id]), follow=True)
        self.assertIn("not allowed", " ".join(self.msgs(resp)))
        self.assertEqual(R.objects.get().status, "PENDING")
        self.login(self.mgr1)
        resp = self.client.post(reverse("stock_approval_reject", args=[req.id]), {"reason": ""}, follow=True)
        self.assertEqual(R.objects.get().status, "PENDING")
        self.client.post(reverse("stock_approval_reject", args=[req.id]), {"reason": "Quantity looks wrong"})
        self.assertEqual(R.objects.get().status, "REJECTED")
        self.login(self.r1)
        resp = self.client.get(reverse("stock_approvals"))
        self.assertContains(resp, "Quantity looks wrong")
        self.assertEqual(self.client.post(reverse("stock_approval_approve", args=[9999])).status_code, 302)

    def test_requester_edit_and_cancel_through_the_inbox(self):
        req = sa.submit_entry(self.r1, self.p, 5, "STAFF")
        self.login(self.r1)
        resp = self.client.get(reverse("stock_approvals"))
        self.assertContains(resp, "Edit or cancel my request")
        self.client.post(reverse("stock_approval_edit", args=[req.id]), {"quantity": 2, "notes": "fixed"})
        self.assertEqual(R.objects.get().quantity, 2)
        self.login(self.mgr1)
        self.client.post(reverse("stock_approval_edit", args=[req.id]), {"quantity": 50})   # not the requester
        self.assertEqual(R.objects.get().quantity, 2)
        self.client.post(reverse("stock_approval_approve", args=[req.id]))
        self.login(self.r1)
        resp = self.client.get(reverse("stock_approvals"))
        self.assertNotContains(resp, "Edit or cancel my request")
        self.client.post(reverse("stock_approval_cancel", args=[req.id]))
        self.assertEqual(R.objects.get().status, "APPROVED")

    def test_batch_buttons(self):
        for i in range(2):
            sa.submit_entry(self.mgr1, self.p, 1 + i, "BRANCH", batch_ref="B77")
        self.login(self.director)
        resp = self.client.get(reverse("stock_approvals"))
        self.assertContains(resp, "Approve all")
        self.client.post(reverse("stock_approval_batch", args=["B77"]), {"action": "reject", "reason": ""})
        self.assertEqual(R.objects.filter(status="PENDING").count(), 2)
        self.client.post(reverse("stock_approval_batch", args=["B77"]), {"action": "approve"})
        self.assertEqual((R.objects.filter(status="APPROVED").count(), self.B()), (2, 3))

    def test_csv_uploads_wait_for_approval(self):
        csv_text = "model_name,category,subcategory,quantity,cost_price,selling_price\nCSV Phone 1,General,General,3,1000,1500\nCSV Phone 2,General,General,0,1000,1500\nCSV Phone 3,General,General,2,900,1200\n"
        self.login(self.mgr1)
        resp = self.client.post(reverse("upload_manager_csv"), {"csv_file": SimpleUploadedFile("s.csv", csv_text.encode())}, follow=True)
        self.assertIn("Submitted 2", " ".join(self.msgs(resp)))
        self.assertIn("1 row", " ".join(self.msgs(resp)))                   # the zero-quantity row is reported
        reqs = R.objects.all()
        self.assertEqual(reqs.count(), 2)
        self.assertEqual(len({r.batch_ref for r in reqs}), 1)
        self.assertTrue(reqs.first().batch_ref)
        self.assertEqual(BranchSafeStock.objects.count(), 0)
        self.login(self.r1)
        retail_csv = "product_name,model_name,category,subcategory,selling_price,quantity,imei_serial\nPh,R CSV 1,General,General,1000,4,\nPh,R CSV 2,General,General,1000,1,\n"
        resp = self.client.post(reverse("upload_retail_csv"), {"csv_file": SimpleUploadedFile("r.csv", retail_csv.encode()), "received_from": "DIRECTOR"}, follow=True)
        rr = R.objects.filter(requested_by=self.r1)
        self.assertEqual((rr.count(), StaffStock.objects.filter(staff=self.r1).count()), (2, 0))
        self.assertTrue(all(r.source_type == "MANUAL_DIRECTOR" for r in rr))
        self.assertEqual(len({r.batch_ref for r in rr}), 1)

    def test_old_manager_csv_overwrite_is_closed(self):
        csv_text = "branch_id,product_id,quantity\n%s,%s,999\n" % (self.b1.id, self.p.id)
        self.login(self.mgr1)
        resp = self.client.post(reverse("upload_stock_csv"), {"csv_file": SimpleUploadedFile("a.csv", csv_text.encode())})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(BranchSafeStock.objects.count(), 0)
        self.login(self.director)
        self.client.post(reverse("upload_stock_csv"), {"csv_file": SimpleUploadedFile("a.csv", csv_text.encode())})
        self.assertEqual(self.B(), 999)                                     # Director's own tool still works

    def test_retail_dashboard_shows_received_from_choice(self):
        self.login(self.r1)
        resp = self.client.get(reverse("retail_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="received_from"', count=2)


class Audit(Base):
    def setUp(self):
        super().setUp()
        self.give_branch(10)
        self.give_branch(4, self.b2)
        self.give_staff(self.r1, 3)
        self.old = sa.submit_entry(self.r1, self.p, 2, "STAFF", source_type="MANUAL_DIRECTOR")          # pending exception
        self.moved = sa.submit_move(self.director, self.p, 2, "DIRECTOR", "BRANCH", to_branch=self.b1)  # normal pending
        sa.approve(self.moved.id, self.mgr1)                                                            # normal approved
        self.rej = sa.submit_entry(self.r3, self.p2, 1, "STAFF")                                        # branch 2 entry
        sa.reject(self.rej.id, self.mgr2, "No paperwork")
        self.red = sa.record_reduction(self.r1, self.p, 1, "damaged")
        R.objects.filter(pk=self.old.pk).update(created_at=timezone.now() - timedelta(days=5))

    def get(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse("stock_audit"), params)

    def ids(self, resp):
        return {r.id for r in resp.context["page"]}

    def test_no_filters_shows_everything(self):
        resp = self.get(self.director)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ids(resp), {self.old.id, self.moved.id, self.rej.id, self.red.id})
        s = resp.context["summary"]
        self.assertEqual((s["pending_count"], s["stale_count"], s["rejected_count"], s["exception_count"]), (1, 1, 1, 3))

    def test_each_filter(self):
        d = self.director
        self.assertEqual(self.ids(self.get(d, status="PENDING")), {self.old.id})
        self.assertEqual(self.ids(self.get(d, status="REJECTED")), {self.rej.id})
        self.assertEqual(self.ids(self.get(d, status="APPROVED")), {self.moved.id, self.red.id})
        self.assertEqual(self.ids(self.get(d, source="NORMAL")), {self.moved.id})
        self.assertEqual(self.ids(self.get(d, source="MANUAL_DIRECTOR")), {self.old.id})
        self.assertEqual(self.ids(self.get(d, branch=self.b2.id)), {self.rej.id})
        self.assertEqual(self.ids(self.get(d, tier="DIRECTOR")), {self.moved.id, self.old.id})
        self.assertEqual(self.ids(self.get(d, staff=self.r3.id)), {self.rej.id})
        self.assertEqual(self.ids(self.get(d, product="itel")), {self.rej.id})
        self.assertEqual(self.ids(self.get(d, date_from=timezone.now().date().isoformat())), {self.moved.id, self.rej.id, self.red.id})
        self.assertEqual(self.ids(self.get(d, date_to=(timezone.now() - timedelta(days=2)).date().isoformat())), {self.old.id})
        self.assertEqual(self.ids(self.get(d, branch=self.b1.id, status="APPROVED", source="NORMAL")), {self.moved.id})   # stacked

    def test_exceptions_button_ignores_status_and_source(self):
        resp = self.get(self.director, exceptions="1", status="APPROVED", source="NORMAL")
        self.assertEqual(self.ids(resp), {self.old.id, self.rej.id, self.red.id})
        self.assertContains(resp, "Exceptions mode")

    def test_holdings_and_totals(self):
        resp = self.get(self.director)
        t = resp.context["totals"]
        self.assertEqual((t["DIRECTOR"], t["BRANCH"], t["STAFF"]), (8, 16, 2))   # 10-2, (10+2)+4, 3-1
        self.assertEqual(resp.context["grand_total_units"], 26)
        self.assertEqual(resp.context["grand_total_value"], 26 * 1000)
        resp = self.get(self.director, branch=self.b1.id)
        self.assertEqual(resp.context["totals"]["DIRECTOR"], 0)
        self.assertEqual(resp.context["totals"]["BRANCH"], 12)
        resp = self.get(self.director, tier="STAFF", staff=self.r1.id)
        self.assertEqual((resp.context["totals"]["STAFF"], resp.context["totals"]["BRANCH"]), (2, 0))

    def test_manager_is_scoped_to_own_branch(self):
        resp = self.get(self.mgr1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ids(resp), {self.old.id, self.moved.id, self.red.id})
        self.assertNotIn(self.rej.id, self.ids(resp))
        resp = self.get(self.mgr1, branch=self.b2.id, tier="DIRECTOR")       # tries to escape
        self.assertNotIn(self.rej.id, self.ids(resp))
        self.assertEqual(resp.context["totals"]["DIRECTOR"], 0)
        self.assertEqual(resp.context["totals"]["BRANCH"], 12)
        self.assertEqual(self.ids(self.get(self.mgr2)), {self.rej.id})

    def test_others_are_refused(self):
        for user in (self.r1, self.tel):
            self.assertEqual(self.get(user).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("stock_audit")).status_code, 302)

    def test_shortfall_is_visible(self):
        req = sa.submit_entry(self.r2, self.p, 4, "STAFF", source_type="MANUAL_DIRECTOR")
        sa.approve(req.id, self.mgr1)
        sa.debit("STAFF", self.p, 3, staff=self.r2)
        sa.reject(req.id, self.director, "Director denies it")
        resp = self.get(self.director)
        self.assertEqual(resp.context["summary"]["shortfall_units"], 3)
        self.assertContains(resp, "shortfall 3")