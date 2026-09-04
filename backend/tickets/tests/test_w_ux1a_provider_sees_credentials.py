"""W-UX1-A — credentials follow the ladder for EVERY viewer.

RECON RESULT, pinned because it is the whole reason this file exists.
Before this change the provider ticket payload carried NO credentials at
all. `_assigned_staff_payload` guarded the block `if is_customer:` and
said so in as many words:

    "M2 P3 (SoT Addendum A.3) — CUSTOMER_USER viewers ONLY: the
     resolver-gated credential / property summary ... Provider viewers
     get NO new keys — their payload is byte-identical to pre-M2."

So only the customer path was ever wired (and W-N1 §4 later wired the
anonymous customer path). A provider looking at their own team's
assignment saw nothing.

THE GRANT QUESTION, answered from the resolver rather than assumed.
`accounts/visibility.py:101-123` is written per role:

    if role in (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN):
        return qs                                    # <- every level
    if role == UserRole.BUILDING_MANAGER:
        return qs.filter(visibility_level__in=(
            VisibilityLevel.PROVIDER_ONLY,
            VisibilityLevel.CUSTOMER_VISIBLE,        # <- no grant join
        ))
    if role == UserRole.CUSTOMER_USER:
        ...
        return qs.filter(
            visibility_level=VisibilityLevel.CUSTOMER_VISIBLE,
            customer_grants__customer=customer,      # <- the ONLY join
        )

The `customer_grants` join appears on the CUSTOMER_USER branch and
nowhere else: grants gate customers, not providers. That is what makes
"Shareable with customers" visible to every provider role by
definition, and it is asserted below rather than trusted.
"""
from __future__ import annotations

import datetime

from rest_framework.test import APITestCase

from accounts.models import (
    StaffCredential,
    StaffProfile,
    UserRole,
    VisibilityLevel,
)
from test_utils import TenantFixtureMixin
from tickets.models import TicketStaffAssignment


class ProviderSeesCredentialsTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker = self.make_user("uxa-worker@example.com", UserRole.STAFF)
        self.profile = StaffProfile.objects.create(user=self.worker)
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.worker, assigned_by=self.company_admin
        )
        self.secret = self._cred(VisibilityLevel.PA_SA_ONLY)
        self.shareable = self._cred(
            VisibilityLevel.CUSTOMER_VISIBLE,
            ctype=StaffCredential.CredentialType.VCA,
        )

    def _cred(self, level, ctype=None):
        return StaffCredential.objects.create(
            staff_profile=self.profile,
            credential_type=ctype or StaffCredential.CredentialType.RESIDENCE_PERMIT,
            visibility_level=level,
            expiry_date=datetime.date.today() + datetime.timedelta(days=200),
        )

    def _levels_seen_by(self, actor):
        self.authenticate(actor)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        rows = [
            r
            for r in response.data["assigned_staff"]
            if not r.get("anonymous") and r.get("id") == self.worker.id
        ]
        self.assertEqual(len(rows), 1, response.data["assigned_staff"])
        return {c["type"] for c in rows[0].get("credentials", [])}

    def test_super_admin_sees_a_pa_sa_only_credential(self):
        types = self._levels_seen_by(self.super_admin)
        self.assertIn(StaffCredential.CredentialType.RESIDENCE_PERMIT, types)

    def test_a_building_manager_does_not_see_pa_sa_only(self):
        """The non-admin provider role. It sees the ladder from
        PROVIDER_ONLY up and no further."""
        types = self._levels_seen_by(self.manager)
        self.assertNotIn(
            StaffCredential.CredentialType.RESIDENCE_PERMIT,
            types,
            "a BUILDING_MANAGER saw a PA_SA_ONLY credential",
        )

    def test_a_provider_sees_customer_visible_without_any_grant(self):
        """No `CredentialCustomerVisibility` row exists in this fixture.
        The resolver's grant join is on the CUSTOMER_USER branch only, so
        both provider roles see it anyway."""
        for actor in (self.super_admin, self.manager, self.company_admin):
            with self.subTest(role=actor.role):
                self.assertIn(
                    StaffCredential.CredentialType.VCA,
                    self._levels_seen_by(actor),
                )

    def test_a_customer_still_needs_the_grant(self):
        """The other half of the same rule, so widening the provider side
        cannot quietly widen the customer side too."""
        types = self._levels_seen_by(self.customer_user)
        self.assertEqual(types, set(), "a customer saw an ungranted credential")
