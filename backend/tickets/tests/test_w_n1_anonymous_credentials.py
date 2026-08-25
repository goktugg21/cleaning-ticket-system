"""W-N1 §4 — a redacted team member still shows what they are qualified for.

RECON RESULT, pinned because it is the whole shape of this change: the
customer-facing credential summary ALREADY existed
(`_staff_credentials_payload_for_customer`, resolver-gated per customer).
What did not reach it was the ANONYMOUS roster: with all three
`show_assigned_staff_*` flags off, `_assigned_staff_payload` returned a
single team-wide label and returned EARLY, and its own comment said that
a fully redacted roster therefore exposed no credentials either.

So this pins the new behaviour AND the redaction that must survive it.
"""
from __future__ import annotations

import datetime

from rest_framework.test import APITestCase

from accounts.models import (
    CredentialCustomerVisibility,
    StaffCredential,
    StaffProfile,
    UserRole,
    VisibilityLevel,
)
from test_utils import TenantFixtureMixin
from tickets.models import TicketStaffAssignment


class AnonymousCredentialsTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # Full redaction: the customer sees no name, email or phone.
        self.customer.show_assigned_staff_name = False
        self.customer.show_assigned_staff_email = False
        self.customer.show_assigned_staff_phone = False
        self.customer.save()

        self.worker = self.make_user("wn1-anon@example.com", UserRole.STAFF)
        self.worker.full_name = "Ayse Yilmaz"
        self.worker.save(update_fields=["full_name"])
        self.profile = StaffProfile.objects.create(
            user=self.worker, phone="+31600000000"
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.worker, assigned_by=self.company_admin
        )
        # `TenantFixtureMixin` already wires `self.customer_user` to
        # `self.customer` with the building access the read needs, and
        # `self.other_customer` is its cross-tenant twin. No second
        # fixture: a hand-rolled one is how a test starts proving
        # something the app never does.

    def _credential(self, *, visibility, ctype=None):
        return StaffCredential.objects.create(
            staff_profile=self.profile,
            credential_type=ctype or StaffCredential.CredentialType.VCA,
            visibility_level=visibility,
            expiry_date=datetime.date.today() + datetime.timedelta(days=365),
        )

    def _roster(self):
        self.authenticate(self.customer_user)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["assigned_staff"]

    def test_customer_visible_credential_is_present(self):
        cred = self._credential(
            visibility=VisibilityLevel.CUSTOMER_VISIBLE
        )
        CredentialCustomerVisibility.objects.create(
            credential=cred, customer=self.customer
        )
        roster = self._roster()
        self.assertEqual(len(roster), 1)
        row = roster[0]
        self.assertTrue(row["anonymous"])
        types = [c["type"] for c in row.get("credentials", [])]
        self.assertIn(StaffCredential.CredentialType.VCA, types)

    def test_pa_sa_only_credential_is_absent(self):
        self._credential(visibility=VisibilityLevel.PA_SA_ONLY)
        row = self._roster()[0]
        self.assertEqual(
            row.get("credentials", []),
            [],
            "a PA_SA_ONLY credential reached a customer",
        )

    def test_a_grant_for_another_customer_does_not_leak(self):
        """The per-customer rule: CUSTOMER_VISIBLE is a ceiling, not a
        grant. Without a row for THIS customer it stays hidden."""
        cred = self._credential(
            visibility=VisibilityLevel.CUSTOMER_VISIBLE
        )
        CredentialCustomerVisibility.objects.create(
            credential=cred, customer=self.other_customer
        )
        row = self._roster()[0]
        self.assertEqual(
            row.get("credentials", []),
            [],
            "another customer's grant made this credential visible",
        )

    def test_no_identity_leaks_anywhere_in_the_row(self):
        cred = self._credential(
            visibility=VisibilityLevel.CUSTOMER_VISIBLE
        )
        CredentialCustomerVisibility.objects.create(
            credential=cred, customer=self.customer
        )
        row = self._roster()[0]
        for forbidden in ("full_name", "email", "phone", "id"):
            self.assertNotIn(
                forbidden, row, f"the anonymous row leaked {forbidden}"
            )
        blob = str(row)
        self.assertNotIn("Ayse", blob)
        self.assertNotIn("wn1-anon@example.com", blob)
        self.assertNotIn("+31600000000", blob)

    def test_one_row_per_member(self):
        second = self.make_user("wn1-anon2@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=second)
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=second, assigned_by=self.company_admin
        )
        # A second slot for the FIRST worker must not make a third row.
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.worker, assigned_by=self.company_admin
        )
        roster = self._roster()
        self.assertEqual(len(roster), 2, roster)
        self.assertTrue(all(r["anonymous"] for r in roster))
