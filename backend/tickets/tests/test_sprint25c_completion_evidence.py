"""
Sprint 25C + B1 — staff completion-evidence rule.

Domain rule: when a STAFF user moves a ticket from IN_PROGRESS to
WAITING_CUSTOMER_APPROVAL (or to WAITING_MANAGER_REVIEW via the
Sprint 28 Batch 11 route), the transition must be accompanied by
EITHER a non-empty completion note OR at least one VISIBLE
attachment already on the ticket. Empty completion (no note + no
visible photo) is rejected with HTTP 400 and a stable error code
`completion_evidence_required`.

"Visible" mirrors the customer-facing attachment filter:
  * is_hidden=False on the TicketAttachment itself, AND
  * the parent TicketMessage (if any) is neither is_hidden=True
    nor message_type=INTERNAL_NOTE.

B1 (system-business-logic-and-workflows.md §4.4) — the gate fires
ONLY for STAFF actors. Managers and admins driving the same
completion transition (BM closing out a job on behalf of an absent
staff member; SUPER_ADMIN unblocking a stuck ticket) bypass the
rule. The pre-B1 "applies independently of role/scope" stance was
wrong per the canonical business doc. See the
`AdminAndManagerBypassCompletionEvidenceTests` class below.

The role/scope gates run BEFORE the evidence check, so an
unauthorised actor (e.g. a CUSTOMER_USER attempting to drive an
OSIUS-side transition) still 403s with `forbidden_transition`,
never reaching the evidence check.
"""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.state_machine import TransitionError, apply_transition


# Tests create on-disk TicketAttachment rows via SimpleUploadedFile,
# which Django's default storage writes under MEDIA_ROOT. The
# project's MEDIA_ROOT is shared with the dev/prod media volume and
# may not be writable by the local test runner — override it to a
# tmp dir so the test suite runs cleanly on any host.
_TMP_MEDIA = tempfile.mkdtemp(prefix="sprint25c-media-")


def _move_to_in_progress(ticket, manager):
    """Drive OPEN -> IN_PROGRESS via the state machine (no evidence
    rule applies to this hop) so subsequent tests start from a state
    where the rule under test can actually fire. The manager arg is
    BUILDING_MANAGER-scoped — only BM/admins can drive OPEN ->
    IN_PROGRESS per ALLOWED_TRANSITIONS."""
    return apply_transition(ticket, manager, TicketStatus.IN_PROGRESS)


def _wire_staff_actor(test_case, ticket):
    """
    B1 — set up a STAFF actor on `test_case` that is allowed to drive
    `IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL` on `ticket`:

      * STAFF user + active StaffProfile,
      * BuildingStaffVisibility on the ticket's building, with
        `staff_completion_routes_to_customer=True` so the route flag
        check in apply_transition admits WAITING_CUSTOMER_APPROVAL as
        the target,
      * TicketStaffAssignment so SCOPE_STAFF_ASSIGNED returns True.

    Stored as `test_case.staff_user` so the rule-fires tests below
    can drive the transition as STAFF and exercise the gate the
    business doc says applies to field staff only.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    staff = User.objects.create_user(
        email=f"staff-25c-{ticket.id}@example.com",
        password=test_case.password,
        role=UserRole.STAFF,
        full_name="Staff 25C",
    )
    StaffProfile.objects.create(user=staff, is_active=True)
    BuildingStaffVisibility.objects.create(
        user=staff,
        building=ticket.building,
        visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        staff_completion_routes_to_customer=True,
    )
    TicketStaffAssignment.objects.create(ticket=ticket, user=staff)
    test_case.staff_user = staff
    return staff


def _make_attachment(ticket, uploader, *, is_hidden=False, message=None):
    """Build a TicketAttachment row with a tiny in-memory file. Body
    is irrelevant — the evidence rule only inspects metadata."""
    return TicketAttachment.objects.create(
        ticket=ticket,
        message=message,
        uploaded_by=uploader,
        file=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff", content_type="image/jpeg"),
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        file_size=3,
        is_hidden=is_hidden,
    )


# ===========================================================================
# Unit-level (apply_transition) coverage — STAFF actor
#
# B1: the completion-evidence rule fires for STAFF only. These tests now
# drive the IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL hop as a STAFF user
# (wired via `_wire_staff_actor`). The setup hop OPEN -> IN_PROGRESS
# stays on `self.manager` because only BM/admins can drive that hop.
# ===========================================================================
@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class CompletionEvidenceUnitTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # The setUp on TenantFixtureMixin already creates self.ticket /
        # self.manager / self.customer. Add a STAFF actor assigned to
        # this ticket so the rule-fires assertions exercise the
        # STAFF-actor path the gate now targets.
        _wire_staff_actor(self, self.ticket)

    def test_transition_with_note_passes(self):
        """A non-empty note alone satisfies the evidence rule."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        result = apply_transition(
            ticket,
            self.staff_user,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="Cleaned and polished, ready for customer review.",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)
        self.assertIsNotNone(result.sent_for_approval_at)

    def test_transition_with_visible_attachment_alone_passes(self):
        """A visible (non-hidden, non-internal-message) attachment
        alone satisfies the rule even with no note."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        _make_attachment(ticket, self.staff_user, is_hidden=False, message=None)

        result = apply_transition(
            ticket,
            self.staff_user,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)

    def test_transition_with_neither_note_nor_attachment_fails(self):
        """Empty completion — no note, no visible attachment — is the
        forbidden case and must raise the typed TransitionError."""
        ticket = _move_to_in_progress(self.ticket, self.manager)

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.staff_user,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                note="",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")
        # Ticket status must not have advanced.
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_whitespace_only_note_does_not_satisfy_rule(self):
        """`note.strip()` is the canonical check — pure whitespace
        is treated as empty."""
        ticket = _move_to_in_progress(self.ticket, self.manager)

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.staff_user,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                note="   \t\n  ",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")

    def test_hidden_attachment_alone_does_not_satisfy_rule(self):
        """An attachment with is_hidden=True is invisible to the
        customer and therefore does NOT count as completion evidence."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        _make_attachment(ticket, self.staff_user, is_hidden=True, message=None)

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.staff_user,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                note="",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")

    def test_internal_note_attachment_alone_does_not_satisfy_rule(self):
        """An attachment hung off an INTERNAL_NOTE message is invisible
        to the customer; the rule must reject it as sole evidence."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        internal_msg = TicketMessage.objects.create(
            ticket=ticket,
            author=self.manager,
            message="internal-only note",
            message_type=TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        _make_attachment(
            ticket, self.staff_user, is_hidden=False, message=internal_msg
        )

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.staff_user,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                note="",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")

    def test_hidden_message_attachment_alone_does_not_satisfy_rule(self):
        """An attachment on an is_hidden TicketMessage (even if
        message_type=PUBLIC_REPLY for some reason) is also invisible
        to the customer and does not satisfy the rule."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        hidden_msg = TicketMessage.objects.create(
            ticket=ticket,
            author=self.manager,
            message="hidden but public-type",
            message_type=TicketMessageType.PUBLIC_REPLY,
            is_hidden=True,
        )
        _make_attachment(
            ticket, self.staff_user, is_hidden=False, message=hidden_msg
        )

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                ticket,
                self.staff_user,
                TicketStatus.WAITING_CUSTOMER_APPROVAL,
                note="",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")

    def test_note_plus_attachment_passes(self):
        """Belt-and-braces: both forms of evidence together are fine
        — no double-counting, no special-case interaction."""
        ticket = _move_to_in_progress(self.ticket, self.manager)
        _make_attachment(ticket, self.staff_user, is_hidden=False, message=None)

        result = apply_transition(
            ticket,
            self.staff_user,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="See attached photo.",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)


# ===========================================================================
# B1 — Admin / manager bypass coverage.
#
# Per system-business-logic-and-workflows.md §4.4 the evidence rule
# applies to STAFF only. Managers and admins driving the same completion
# transition (e.g. BM closing a job on behalf of an absent staff member,
# SUPER_ADMIN unblocking a stuck ticket) must NOT trip the gate even
# with empty note + no visible attachment.
# ===========================================================================
@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class AdminAndManagerBypassCompletionEvidenceTests(TenantFixtureMixin, APITestCase):
    def test_building_manager_bypasses_evidence_rule(self):
        ticket = _move_to_in_progress(self.ticket, self.manager)
        result = apply_transition(
            ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)

    def test_company_admin_bypasses_evidence_rule(self):
        ticket = _move_to_in_progress(self.ticket, self.manager)
        result = apply_transition(
            ticket,
            self.company_admin,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)

    def test_super_admin_bypasses_evidence_rule(self):
        ticket = _move_to_in_progress(self.ticket, self.manager)
        result = apply_transition(
            ticket,
            self.super_admin,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note="",
        )
        self.assertEqual(result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL)


# ===========================================================================
# API-level (POST /api/tickets/<id>/status/) coverage — confirms the
# error envelope and that the auth gate fires BEFORE the evidence check.
# ===========================================================================
@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class CompletionEvidenceAPITests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # B1 — the evidence-required path now fires only for STAFF.
        # Wire a STAFF actor against self.ticket so the API-level
        # assertions exercise the gate via the role it applies to.
        _wire_staff_actor(self, self.ticket)

    def _drive_to_in_progress(self):
        return _move_to_in_progress(self.ticket, self.manager)

    def test_api_returns_400_with_stable_code_when_evidence_missing(self):
        in_progress = self._drive_to_in_progress()
        self.authenticate(self.staff_user)
        response = self.client.post(
            f"/api/tickets/{in_progress.id}/status/",
            {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # DRF wraps the serializer ValidationError dict; the
        # `detail` key carries the human message and `code` carries
        # the stable string clients should branch on.
        # The serializer's save() wraps via `{"detail": ..., "code": ...}`.
        body = response.json()
        # Either the top-level keys are present (depends on DRF version),
        # or they're nested under a list. Be permissive on shape but
        # strict on the code value's presence.
        flat = body if isinstance(body, dict) else {}
        nested_code = None
        if isinstance(flat.get("code"), list):
            nested_code = flat["code"][0]
        elif isinstance(flat.get("code"), str):
            nested_code = flat["code"]
        self.assertEqual(
            nested_code,
            "completion_evidence_required",
            f"Unexpected error envelope: {body!r}",
        )

    def test_api_passes_with_note(self):
        in_progress = self._drive_to_in_progress()
        self.authenticate(self.staff_user)
        response = self.client.post(
            f"/api/tickets/{in_progress.id}/status/",
            {
                "to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL,
                "note": "Done — please confirm.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_api_admin_bypasses_evidence_rule(self):
        # B1 — same endpoint, COMPANY_ADMIN actor, empty payload. The
        # gate must NOT fire; the transition succeeds.
        in_progress = self._drive_to_in_progress()
        self.authenticate(self.company_admin)
        response = self.client.post(
            f"/api/tickets/{in_progress.id}/status/",
            {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_customer_user_blocked_by_auth_gate_not_evidence_gate(self):
        """A CUSTOMER_USER never has the OSIUS-side transition right
        in the first place. The view's role gate must still 403/400
        BEFORE the evidence check fires — i.e. the response must NOT
        carry `completion_evidence_required`."""
        in_progress = self._drive_to_in_progress()
        self.authenticate(self.customer_user)
        response = self.client.post(
            f"/api/tickets/{in_progress.id}/status/",
            {"to_status": TicketStatus.WAITING_CUSTOMER_APPROVAL},
            format="json",
        )
        # The view's pre-serializer gate raises PermissionDenied for
        # non-staff customers attempting non-{APPROVED,REJECTED} hops,
        # which DRF maps to 403.
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST),
            f"Unexpected status for unauthorised actor: {response.status_code} "
            f"body={response.content!r}",
        )
        # And critically: the error must NOT be the evidence code,
        # because the auth gate runs first.
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            body = response.json()
            code = body.get("code")
            if isinstance(code, list):
                code = code[0] if code else None
            self.assertNotEqual(code, "completion_evidence_required")
