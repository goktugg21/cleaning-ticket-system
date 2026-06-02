"""
Sprint 12B Batch 3 — audit coverage for promote-to-user (link mode).

H-10: every scope-changing mutation writes an AuditLog row. Promoting a
contact in link mode (a) flips `Contact.user` (full-CRUD trio → UPDATE
diff carrying `user`), and (b) materialises a `CustomerUserMembership`
+ `CustomerUserBuildingAccess` row (membership-shape CREATE rows).

The promote MUST go through the authenticated API client so the audit
actor is captured from `request.user` — calling the service directly
would leave `actor=None` (correct semantics for a system write, wrong
for this test).
"""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserRole
from audit.models import AuditAction, AuditLog
from customers.models import (
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)

from ._promote_base import PromoteContactFixtureMixin


class PromoteLinkAuditTests(PromoteContactFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.spare = self.make_user(
            "audit-spare@example.com", UserRole.CUSTOMER_USER
        )
        self.contact = self.make_contact(
            full_name="Audit Spare", email="audit-spare@example.com"
        )
        self.authenticate(self.super_admin)
        # Link the contact to building A, then wipe the audit baseline so
        # the promote is measured from zero.
        self.client.patch(
            self.contact_detail_url(self.contact.id),
            {"building_ids": [self.building.id]},
            format="json",
        )
        self.contact.refresh_from_db()
        AuditLog.objects.all().delete()

    def _promote(self):
        response = self.client.post(
            self.promote_url(self.contact.id), {}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["mode"], "linked")
        return response

    # 25 — Contact UPDATE row carries the user FK flip -------------------
    def test_promote_writes_contact_user_update_log(self):
        self._promote()

        logs = AuditLog.objects.filter(
            target_model="customers.Contact",
            target_id=self.contact.id,
            action=AuditAction.UPDATE,
        )
        self.assertTrue(logs.exists())
        # The UPDATE diff carrying the user flip.
        user_logs = [log for log in logs if "user" in log.changes]
        self.assertEqual(
            len(user_logs),
            1,
            "Expected exactly one Contact UPDATE log carrying the user flip.",
        )
        log = user_logs[0]
        self.assertEqual(log.actor, self.super_admin)
        self.assertIsNone(log.changes["user"]["before"])
        self.assertEqual(log.changes["user"]["after"], self.spare.id)

    # 26 — membership + CUBA CREATE rows, exactly one each ---------------
    def test_promote_writes_membership_and_access_create_logs(self):
        self._promote()

        membership = CustomerUserMembership.objects.get(
            customer=self.customer, user=self.spare
        )
        access = CustomerUserBuildingAccess.objects.get(
            membership=membership, building=self.building
        )

        membership_logs = AuditLog.objects.filter(
            target_model="customers.CustomerUserMembership",
            target_id=membership.id,
            action=AuditAction.CREATE,
        )
        self.assertEqual(
            membership_logs.count(),
            1,
            "Expected exactly one CustomerUserMembership CREATE log.",
        )
        m_log = membership_logs.get()
        self.assertEqual(m_log.actor, self.super_admin)
        self.assertEqual(m_log.changes["user_email"]["after"], self.spare.email)
        self.assertEqual(
            m_log.changes["customer_id"]["after"], self.customer.id
        )

        access_logs = AuditLog.objects.filter(
            target_model="customers.CustomerUserBuildingAccess",
            target_id=access.id,
            action=AuditAction.CREATE,
        )
        self.assertEqual(
            access_logs.count(),
            1,
            "Expected exactly one CustomerUserBuildingAccess CREATE log.",
        )
        a_log = access_logs.get()
        self.assertEqual(a_log.actor, self.super_admin)
        self.assertEqual(a_log.changes["user_email"]["after"], self.spare.email)
        self.assertEqual(a_log.changes["building_id"]["after"], self.building.id)
