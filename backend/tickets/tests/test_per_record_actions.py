"""
Per-record actions backend — ticket detail `actions` block.

Pins the contract that the new `actions` SerializerMethodField on
`TicketDetailSerializer` exposes:

  * `allowed_next_statuses` equals the top-level field of the same
    name (the two share a single computation; this prevents drift).
  * `can_post_provider_internal_note` is True for SA / CA / BM in
    scope; False for STAFF and for CUSTOMER_USER.
  * `can_post_staff_operational_note` and `can_post_staff_completion_note`
    are True for any provider-side actor (incl. STAFF).
  * `can_upload_hidden_attachment` is provider-management only.
  * `can_override_customer_decision` reflects the B6 revocable key
    state for BM (False when the per-(BM, building) override is off).
  * `status_transitions` is an O(1) lookup dict whose True entries
    are exactly `allowed_next_statuses`.

The booleans are the live answers — they mirror the same resolvers
that the underlying state machine and write validators consult, so
the per-record answer cannot drift from "what happens when I POST".
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    Ticket,
    TicketStaffAssignment,
    TicketStatus,
)


class TicketActionsBlockTests(TenantFixtureMixin, APITestCase):
    """Verifies the contract of the new `actions` block on ticket
    detail responses."""

    def _detail(self, user, ticket=None):
        ticket = ticket or self.ticket
        self.authenticate(user)
        response = self.client.get(f"/api/tickets/{ticket.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    # -----------------------------------------------------------------
    # actions.allowed_next_statuses agrees with top-level field
    # -----------------------------------------------------------------
    def test_actions_allowed_next_statuses_equals_top_level(self):
        # Move the ticket forward so the action surface is non-trivial.
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status", "updated_at"])

        for actor in (
            self.super_admin,
            self.company_admin,
            self.manager,
            self.customer_user,
        ):
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertEqual(
                    data["actions"]["allowed_next_statuses"],
                    data["allowed_next_statuses"],
                    f"actions block drifted from top-level field for {actor.email}",
                )
                # `status_transitions` True entries must exactly match
                # the allowed list — same source of truth.
                allowed_set = set(data["allowed_next_statuses"])
                map_true = {
                    s for s, v in data["actions"]["status_transitions"].items() if v
                }
                self.assertEqual(map_true, allowed_set)

    # -----------------------------------------------------------------
    # Note booleans — mirror message_type write-validation matrix
    # -----------------------------------------------------------------
    def test_can_post_provider_internal_note_true_for_sa_ca_bm(self):
        for actor in (self.super_admin, self.company_admin, self.manager):
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertTrue(
                    data["actions"]["can_post_provider_internal_note"],
                    f"{actor.email} should be allowed to post INTERNAL_NOTE",
                )

    def test_can_post_provider_internal_note_false_for_staff_and_customer(self):
        # Build a STAFF user with visibility on the ticket's building
        # so they actually reach the detail endpoint.
        staff_user = self.make_user("staff-action@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=staff_user)
        BuildingStaffVisibility.objects.create(
            user=staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=staff_user, assigned_by=self.manager
        )
        for actor in (staff_user, self.customer_user):
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertFalse(
                    data["actions"]["can_post_provider_internal_note"],
                    f"{actor.email} should NOT be allowed to post INTERNAL_NOTE",
                )

    def test_can_post_staff_notes_true_for_provider_side_incl_staff(self):
        # STAFF + every provider-management role.
        staff_user = self.make_user("staff-action-2@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=staff_user)
        BuildingStaffVisibility.objects.create(
            user=staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=staff_user, assigned_by=self.manager
        )
        for actor in (self.super_admin, self.company_admin, self.manager, staff_user):
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertTrue(data["actions"]["can_post_staff_operational_note"])
                self.assertTrue(data["actions"]["can_post_staff_completion_note"])

    def test_can_post_staff_notes_false_for_customer(self):
        data = self._detail(self.customer_user)
        self.assertFalse(data["actions"]["can_post_staff_operational_note"])
        self.assertFalse(data["actions"]["can_post_staff_completion_note"])

    # -----------------------------------------------------------------
    # Hidden attachment — provider management only.
    # -----------------------------------------------------------------
    def test_can_upload_hidden_attachment_provider_management_only(self):
        staff_user = self.make_user("staff-hidden@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=staff_user)
        BuildingStaffVisibility.objects.create(
            user=staff_user, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=staff_user, assigned_by=self.manager
        )
        true_cases = [self.super_admin, self.company_admin, self.manager]
        false_cases = [staff_user, self.customer_user]
        for actor in true_cases:
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertTrue(data["actions"]["can_upload_hidden_attachment"])
        for actor in false_cases:
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertFalse(data["actions"]["can_upload_hidden_attachment"])

    # -----------------------------------------------------------------
    # Customer-decision override — BM revocable key (B6).
    # The tightened action boolean now requires the ticket to be at the
    # customer-decision step (WAITING_CUSTOMER_APPROVAL with APPROVED /
    # REJECTED reachable in the live state machine) — pure authority
    # is not enough. Move the fixture ticket into WCA via the helper
    # for the positive-authority cases below.
    # -----------------------------------------------------------------
    def test_can_override_customer_decision_for_sa_and_ca(self):
        # Move into WAITING_CUSTOMER_APPROVAL — tightened boolean now
        # requires the ticket to be at the customer-decision step.
        self.move_ticket_to_customer_approval()
        for actor in (self.super_admin, self.company_admin):
            with self.subTest(actor=actor.email):
                data = self._detail(actor)
                self.assertTrue(data["actions"]["can_override_customer_decision"])

    def test_can_override_customer_decision_bm_default_true(self):
        # Default: no override map -> resolver returns True for an
        # assigned BM. Ticket moved to WCA so the tightened boolean
        # actually answers True.
        self.move_ticket_to_customer_approval()
        data = self._detail(self.manager)
        self.assertTrue(data["actions"]["can_override_customer_decision"])

    def test_can_override_customer_decision_bm_revoked_false(self):
        # Flip the per-(BM, building) override key to False — the
        # per-record action must update accordingly. Ticket moved to
        # WCA so the test isolates the authority-revoke effect (without
        # the WCA precondition the result is False either way).
        self.move_ticket_to_customer_approval()
        assignment = BuildingManagerAssignment.objects.get(
            user=self.manager, building=self.building
        )
        assignment.permission_overrides = {
            "osius.building_manager.override_customer_decision": False,
        }
        assignment.save(update_fields=["permission_overrides"])

        data = self._detail(self.manager)
        self.assertFalse(
            data["actions"]["can_override_customer_decision"],
            "BM with override key revoked must see False here",
        )

    def test_can_override_customer_decision_false_for_customer_user(self):
        # Customer never holds override authority regardless of status.
        self.move_ticket_to_customer_approval()
        data = self._detail(self.customer_user)
        self.assertFalse(data["actions"]["can_override_customer_decision"])

    # -----------------------------------------------------------------
    # Tightened-precondition tests: override boolean is False outside
    # the customer-decision step (WAITING_CUSTOMER_APPROVAL) even for
    # actors who hold full override authority.
    # -----------------------------------------------------------------
    def test_can_override_customer_decision_false_outside_wca_for_super_admin(self):
        # Default fixture status is OPEN — not the customer-decision step.
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)
        data = self._detail(self.super_admin)
        self.assertFalse(
            data["actions"]["can_override_customer_decision"],
            "SA must see False on an OPEN ticket — authority alone is not enough",
        )

    def test_can_override_customer_decision_false_in_progress_for_super_admin(self):
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status", "updated_at"])
        data = self._detail(self.super_admin)
        self.assertFalse(
            data["actions"]["can_override_customer_decision"],
            "SA must see False on an IN_PROGRESS ticket",
        )

    def test_can_override_customer_decision_false_on_approved_for_company_admin(self):
        self.ticket.status = TicketStatus.APPROVED
        self.ticket.save(update_fields=["status", "updated_at"])
        data = self._detail(self.company_admin)
        self.assertFalse(
            data["actions"]["can_override_customer_decision"],
            "CA must see False on an already-APPROVED ticket",
        )

    def test_can_override_customer_decision_false_on_open_for_bm_with_override_key(self):
        # BM holds the override key by default, but the ticket is OPEN
        # so the action boolean is still False — the answer is precise
        # to THIS ticket's current state, not just authority.
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)
        data = self._detail(self.manager)
        self.assertFalse(
            data["actions"]["can_override_customer_decision"],
            "BM-with-override-key must see False on an OPEN ticket",
        )

    # -----------------------------------------------------------------
    # status_transitions completeness — every status appears as a key.
    # -----------------------------------------------------------------
    def test_status_transitions_covers_every_status_in_enum(self):
        data = self._detail(self.super_admin)
        # Every status from the TicketStatus enum must be a key in the
        # status_transitions map. The frontend reads this as an O(1)
        # lookup; missing keys would cause undefined-property errors.
        enum_values = {str(s) for s, _label in TicketStatus.choices}
        map_keys = set(data["actions"]["status_transitions"].keys())
        self.assertEqual(enum_values, map_keys)
