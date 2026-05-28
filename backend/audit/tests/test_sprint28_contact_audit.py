"""
Sprint 28 Batch 4 — Contact (customers.Contact) audit-coverage tests.

Contact is registered with the full-CRUD signal trio
(`_on_pre_save` / `_on_post_save` / `_on_post_delete`) in
`backend/audit/signals.py`. The tests below exercise the API entrypoints
end-to-end and assert that exactly one AuditLog row lands per mutation,
with the actor, action, target_model, target_id and changes shape we
expect.
"""
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditAction, AuditLog
from customers.models import Contact
from test_utils import TenantFixtureMixin


class ContactAuditCoverageTests(TenantFixtureMixin, APITestCase):
    URL_LIST_TMPL = "/api/customers/{customer_id}/contacts/"
    URL_DETAIL_TMPL = "/api/customers/{customer_id}/contacts/{contact_id}/"

    def setUp(self):
        super().setUp()
        # The fixture's create() calls have already populated AuditLog
        # rows; drop them so every test starts with a clean slate.
        AuditLog.objects.all().delete()

    def test_contact_create_via_api_writes_create_audit_log(self):
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL_LIST_TMPL.format(customer_id=self.customer.id),
            {
                "full_name": "Audit Jane",
                "email": "jane@audit.example",
                "phone": "+31 6 1234 5678",
                "role_label": "Receptionist",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        logs = AuditLog.objects.filter(target_model="customers.Contact")
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, AuditAction.CREATE)
        self.assertEqual(log.actor, self.super_admin)
        self.assertEqual(log.target_id, response.data["id"])
        # CREATE-shape diffs put new values in `after`, None in `before`.
        self.assertIn("full_name", log.changes)
        self.assertEqual(log.changes["full_name"]["after"], "Audit Jane")
        self.assertIsNone(log.changes["full_name"]["before"])
        # The customer FK is captured as the pk.
        self.assertEqual(log.changes["customer"]["after"], self.customer.id)

    def test_contact_update_via_api_writes_update_audit_log(self):
        contact = Contact.objects.create(
            customer=self.customer, full_name="Before Name"
        )
        AuditLog.objects.all().delete()  # drop the CREATE row above

        self.authenticate(self.super_admin)
        response = self.client.patch(
            self.URL_DETAIL_TMPL.format(
                customer_id=self.customer.id, contact_id=contact.id
            ),
            {"full_name": "After Name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = AuditLog.objects.filter(
            target_model="customers.Contact",
            target_id=contact.id,
            action=AuditAction.UPDATE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        # Only the changed field is in the diff — created_at / updated_at
        # are auto-managed and filtered out by audit/diff.py NOISY_FIELDS.
        self.assertEqual(set(log.changes.keys()), {"full_name"})
        self.assertEqual(log.changes["full_name"]["before"], "Before Name")
        self.assertEqual(log.changes["full_name"]["after"], "After Name")

    def test_contact_delete_via_api_writes_delete_audit_log(self):
        contact = Contact.objects.create(
            customer=self.customer,
            full_name="To Be Deleted",
            phone="+31 6 9999 9999",
        )
        contact_id = contact.id
        AuditLog.objects.all().delete()  # drop the CREATE row above

        self.authenticate(self.super_admin)
        response = self.client.delete(
            self.URL_DETAIL_TMPL.format(
                customer_id=self.customer.id, contact_id=contact_id
            )
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        log = AuditLog.objects.filter(
            target_model="customers.Contact",
            target_id=contact_id,
            action=AuditAction.DELETE,
        ).get()
        self.assertEqual(log.actor, self.super_admin)
        # DELETE-shape diffs put old values in `before`, None in `after`.
        self.assertEqual(log.changes["full_name"]["before"], "To Be Deleted")
        self.assertIsNone(log.changes["full_name"]["after"])
        self.assertEqual(log.changes["phone"]["before"], "+31 6 9999 9999")

    def test_contact_audit_log_carries_no_sensitive_fields(self):
        # Contact has no auth-shaped columns by design. The
        # SENSITIVE_FIELD_TOKENS redaction in audit/diff.py is a
        # belt-and-braces safety net; this test pins the contract so a
        # future refactor that accidentally adds `password` /
        # `token` / `secret` / etc. on Contact still does not leak.
        self.authenticate(self.super_admin)
        response = self.client.post(
            self.URL_LIST_TMPL.format(customer_id=self.customer.id),
            {"full_name": "No Secrets Here"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = AuditLog.objects.filter(target_model="customers.Contact").get()
        forbidden = ("password", "token", "secret", "hash", "otp", "mfa")
        for key in log.changes:
            lowered = key.lower()
            for token in forbidden:
                self.assertNotIn(
                    token,
                    lowered,
                    f"Sensitive field {key!r} leaked into Contact audit changes",
                )
