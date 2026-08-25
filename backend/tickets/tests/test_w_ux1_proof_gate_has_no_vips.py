"""W-UX1 §4 — the completion proof gate binds every role.

RECON, PINNED HERE BECAUSE THE BRIEF NAMED THE WRONG FILE.
`transition_requirements.py` has DEFINED `REQ_COMPLETION_EVIDENCE` since
W13-FIX and never once appended it: its module docstring promised
"-> WAITING_* needs the completion evidence ... surfaced here so the
MODAL can show it", and the code never surfaced it. The live rule was
`state_machine.py:653` -- `if getattr(user, "role", None) ==
UserRole.STAFF and ...` -- whose own comment said the scoping was
deliberate and spelled out the consequence: "a manager can still
complete a job that requires a photo without one."

THE OLD ASSERTION, quoted so the change of intent survives. Three tests
in `test_sprint25c_completion_evidence.py` pinned the exemption:

    test_building_manager_bypasses_evidence_rule
    test_company_admin_bypasses_evidence_rule
    test_super_admin_bypasses_evidence_rule

each asserting the transition SUCCEEDS with `note=""` and no
attachment. All three still pass and still should -- they call
`apply_transition` directly, and that primitive is unchanged on purpose:
`auto_close`, the sub-task rollup and the extra-work sync hook drive it
with no operator present.

What changed is the OPERATOR'S DOOR. `POST /api/tickets/<id>/status/`
now refuses a provider completing without proof, and the only way past
is the explicit override, whose reason is recorded on the status-history
row.
"""
from __future__ import annotations

import tempfile

from django.test import override_settings
from rest_framework.test import APITestCase

from test_utils import TenantFixtureMixin
from tickets.models import TicketStatus, TicketStatusHistory
from tickets.state_machine import apply_transition

_TMP_MEDIA = tempfile.mkdtemp(prefix="w-ux1-media-")


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class ProofGateHasNoVipsTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        apply_transition(
            self.ticket, self.manager, TicketStatus.IN_PROGRESS, note="setup"
        )
        self.ticket.refresh_from_db()

    def _url(self):
        return f"/api/tickets/{self.ticket.id}/status/"

    def _post(self, actor, **extra):
        self.authenticate(actor)
        body = {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL}
        body.update(extra)
        return self.client.post(self._url(), body, format="json")

    def test_a_provider_is_blocked_without_proof(self):
        response = self._post(self.company_admin)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data.get("code"), "transition_requirements_unmet", response.data
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.IN_PROGRESS)

    def test_a_super_admin_is_blocked_too(self):
        """The VIP the ruling is named after."""
        response = self._post(self.super_admin)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data.get("code"), "transition_requirements_unmet", response.data
        )

    def test_a_provider_passes_with_proof(self):
        response = self._post(self.company_admin, note="Work finished, floor dry.")
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)

    def test_the_override_passes_and_its_reason_is_recorded(self):
        reason = "Customer confirmed by phone; photo lost with the old handset."
        response = self._post(
            self.super_admin, is_override=True, override_reason=reason
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        row = (
            TicketStatusHistory.objects.filter(
                ticket=self.ticket, new_status=TicketStatus.WAITING_CUSTOMER_APPROVAL
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertTrue(row.is_override, "the override was not recorded as one")
        self.assertEqual(row.override_reason, reason)

    def test_an_override_with_no_reason_is_still_refused(self):
        """The bypass costs a sentence or it is not a bypass."""
        response = self._post(self.super_admin, is_override=True)
        self.assertEqual(response.status_code, 400, response.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.IN_PROGRESS)
