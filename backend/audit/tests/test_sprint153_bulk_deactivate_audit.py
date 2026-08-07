"""
Sprint 153 §2.5 — the bulk customer deactivate writes one AuditLog row
per customer.

`Customer` is already in the audit full-CRUD trio with generic field
introspection, so `is_active` needs no `_*_TRACKED_FIELDS` entry and
`audit/signals.py` is untouched by this sprint. What this file pins is
the thing that WOULD silently break that: the endpoint must call a real
`save()` per row. A queryset `.update()` fires no pre_save/post_save and
therefore writes ZERO audit rows (H-10) — the trap
`ServiceCategoryArchiveView` set the precedent for and the Sprint 152
timesheets multiplier refresh fell into.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from customers.models import Customer
from test_utils import TenantFixtureMixin


BULK_DEACTIVATE_URL = "/api/customers/bulk-deactivate/"


class BulkDeactivateAuditTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.targets = [
            Customer.objects.create(company=self.company, name=f"Audit Target {i}")
            for i in range(3)
        ]

    def _customer_update_logs(self):
        return AuditLog.objects.filter(
            target_model="customers.Customer",
            action=AuditAction.UPDATE,
        )

    def test_bulk_deactivate_of_three_customers_writes_three_audit_rows(self):
        self.authenticate(self.super_admin)
        before = self._customer_update_logs().count()

        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [c.id for c in self.targets]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"deactivated": 3})

        logs = self._customer_update_logs().filter(
            target_id__in=[c.id for c in self.targets]
        )
        self.assertEqual(
            logs.count(),
            3,
            "expected one AuditLog row per deactivated customer; a queryset "
            ".update() would have written none",
        )
        self.assertEqual(self._customer_update_logs().count(), before + 3)

        for log in logs:
            self.assertEqual(log.actor_id, self.super_admin.id)
            self.assertIn("is_active", log.changes)
            self.assertIs(log.changes["is_active"]["before"], True)
            self.assertIs(log.changes["is_active"]["after"], False)

    def test_rejected_batch_writes_no_audit_rows(self):
        """A 400 means nothing was written, so nothing is audited."""
        self.authenticate(self.company_admin)
        before = self._customer_update_logs().count()

        response = self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.targets[0].id, self.other_customer.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._customer_update_logs().count(), before)

    def test_audit_rows_carry_the_bulk_reason(self):
        self.authenticate(self.super_admin)
        self.client.post(
            BULK_DEACTIVATE_URL,
            {"customers": [self.targets[0].id]},
            format="json",
        )
        log = self._customer_update_logs().get(
            target_id=self.targets[0].id
        )
        self.assertEqual(log.reason, "customer_bulk_deactivate")
