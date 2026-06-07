"""
B7 — four-tier note taxonomy on `TicketMessage` + status-history
PROVIDER_INTERNAL redaction for STAFF.

Reference: `docs/product/system-business-logic-and-workflows.md` §9.

The four tiers on `TicketMessageType`:

  * `PUBLIC_REPLY`       — CUSTOMER_VISIBLE
  * `INTERNAL_NOTE`      — PROVIDER_INTERNAL
  * `STAFF_OPERATIONAL`  — STAFF_OPERATIONAL
  * `STAFF_COMPLETION`   — STAFF_COMPLETION

Visibility rules (in scope):

  * Provider management (SA / COMPANY_ADMIN / BUILDING_MANAGER): sees
    every tier including hidden moderation rows.
  * STAFF: sees PUBLIC_REPLY + STAFF_OPERATIONAL + STAFF_COMPLETION.
    Does NOT see INTERNAL_NOTE messages, their attachments, or
    PROVIDER_INTERNAL override commentary on status-history rows.
  * Customer-side users (CUSTOMER_USER): sees PUBLIC_REPLY +
    STAFF_COMPLETION only.

Write rules:

  * `INTERNAL_NOTE` author must be provider management. STAFF and
    customer-side actors cannot create one.
  * `STAFF_OPERATIONAL` / `STAFF_COMPLETION` author must be a
    provider-side actor (provider management or STAFF). Customer-side
    actors cannot create one (the view force-normalises their message
    to PUBLIC_REPLY before the validator fires).
  * `is_hidden=True` on an attachment requires provider management
    (defence-in-depth: STAFF cannot hide an attachment because STAFF
    also cannot see hidden attachments in their own queryset).

Pinned tests:

  A. Default taxonomy + visibility per tier.
  B. Write-time validation for each tier per actor role.
  C. Attachment download gate per tier.
  D. Status-history PROVIDER_INTERNAL override redaction for STAFF.
  E. Staff completion-evidence rule respects the four-tier taxonomy
     (PROVIDER_INTERNAL and STAFF_OPERATIONAL attachments don't satisfy
     the rule; STAFF_COMPLETION attachments do).
  F. URL-smuggling regression — direct URL attempts on every visibility
     boundary cannot leak PROVIDER_INTERNAL content.

No frontend changes. One migration
(`tickets/0011_b7_message_type_four_tier_taxonomy.py`).
"""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from accounts.permissions import (
    is_provider_management_role,
    is_staff_role,
)
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStaffAssignment,
    TicketStatus,
    TicketStatusHistory,
)


def _mk_attachment(ticket, uploader, *, is_hidden=False, message=None):
    return TicketAttachment.objects.create(
        ticket=ticket,
        uploaded_by=uploader,
        file=SimpleUploadedFile(
            "evidence.pdf", b"%PDF-1.4", content_type="application/pdf"
        ),
        original_filename="evidence.pdf",
        mime_type="application/pdf",
        file_size=8,
        is_hidden=is_hidden,
        message=message,
    )


def _msg(ticket, author, body, message_type, **kwargs):
    return TicketMessage.objects.create(
        ticket=ticket,
        author=author,
        message=body,
        message_type=message_type,
        is_hidden=(
            kwargs.get(
                "is_hidden",
                message_type == TicketMessageType.INTERNAL_NOTE,
            )
        ),
    )


class _B7Fixture(TenantFixtureMixin, APITestCase):
    """Extends the shared tenant fixture (Company A + Building A +
    Customer A + Manager + Customer User + Ticket) with one STAFF
    user in scope for the building. The fixture's `self.manager` is
    the BM; `self.company_admin` is the Provider Company Admin;
    `self.super_admin` is the Super Admin; `self.customer_user` is
    the customer-side user."""

    def setUp(self):
        super().setUp()
        self.staff_user = self.make_user(
            "staff-b7@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=self.staff_user, is_active=True)
        BuildingStaffVisibility.objects.create(
            user=self.staff_user, building=self.building
        )

    def _messages_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/messages/"

    def _attachments_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/attachments/"

    def _attachment_download_url(self, ticket, attachment):
        return (
            f"/api/tickets/{ticket.id}/attachments/{attachment.id}/download/"
        )

    def _ticket_detail_url(self, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/"


# ---------------------------------------------------------------------------
# A. Default taxonomy + visibility per tier (READ)
# ---------------------------------------------------------------------------
class MessageVisibilityPerTierTests(_B7Fixture):
    def setUp(self):
        super().setUp()
        # Seed one message per tier.
        self.public_msg = _msg(
            self.ticket, self.customer_user, "Hello", TicketMessageType.PUBLIC_REPLY
        )
        self.internal_msg = _msg(
            self.ticket,
            self.manager,
            "Cost is EUR 120",
            TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        self.staff_op_msg = _msg(
            self.ticket,
            self.manager,
            "Bring a ladder",
            TicketMessageType.STAFF_OPERATIONAL,
        )
        self.staff_completion_msg = _msg(
            self.ticket,
            self.staff_user,
            "Done at 14:30",
            TicketMessageType.STAFF_COMPLETION,
        )

    def _visible_ids(self, response):
        data = response.data.get("results", response.data)
        return {item["id"] for item in data}

    def test_provider_management_sees_all_tiers(self):
        for actor in (self.super_admin, self.company_admin, self.manager):
            self.authenticate(actor)
            response = self.client.get(self._messages_url())
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                self._visible_ids(response),
                {
                    self.public_msg.id,
                    self.internal_msg.id,
                    self.staff_op_msg.id,
                    self.staff_completion_msg.id,
                },
                f"actor={actor.email} should see all four tiers",
            )

    def test_staff_sees_operational_completion_not_public_or_internal(self):
        # M1 B5 — STAFF visibility narrowed to STAFF_OPERATIONAL +
        # STAFF_COMPLETION. PUBLIC_REPLY is now provider/customer-only (a
        # field worker has no customer-conversation channel); INTERNAL_NOTE
        # stays provider-management only.
        self.authenticate(self.staff_user)
        response = self.client.get(self._messages_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._visible_ids(response),
            {
                self.staff_op_msg.id,
                self.staff_completion_msg.id,
            },
        )
        # STAFF must NOT see the PUBLIC_REPLY (customer-conversation channel).
        self.assertNotIn(self.public_msg.id, self._visible_ids(response))
        # Defence-in-depth: explicit assertion the body of INTERNAL_NOTE
        # never leaks.
        data = response.data.get("results", response.data)
        for item in data:
            self.assertNotIn("Cost is EUR 120", item.get("message", ""))

    def test_customer_sees_public_and_staff_completion_only(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self._messages_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self._visible_ids(response),
            {self.public_msg.id, self.staff_completion_msg.id},
        )


# ---------------------------------------------------------------------------
# B. Write-time validation per tier
# ---------------------------------------------------------------------------
class MessageWriteValidationTests(_B7Fixture):
    def _post_message(self, body, message_type):
        return self.client.post(
            self._messages_url(),
            {"message": body, "message_type": message_type},
            format="json",
        )

    def test_provider_management_can_post_internal_note(self):
        for actor in (self.super_admin, self.company_admin, self.manager):
            self.authenticate(actor)
            response = self._post_message(
                f"internal {actor.email}",
                TicketMessageType.INTERNAL_NOTE,
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                f"actor={actor.email}: {response.content!r}",
            )
            row = TicketMessage.objects.get(pk=response.data["id"])
            self.assertEqual(
                row.message_type, TicketMessageType.INTERNAL_NOTE
            )
            self.assertTrue(row.is_hidden)

    def test_staff_cannot_post_internal_note(self):
        self.authenticate(self.staff_user)
        response = self._post_message(
            "smuggled internal", TicketMessageType.INTERNAL_NOTE
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.content
        )
        self.assertFalse(
            TicketMessage.objects.filter(
                ticket=self.ticket,
                author=self.staff_user,
                message_type=TicketMessageType.INTERNAL_NOTE,
            ).exists()
        )

    def test_customer_user_cannot_post_internal_note(self):
        self.authenticate(self.customer_user)
        response = self._post_message(
            "smuggled internal", TicketMessageType.INTERNAL_NOTE
        )
        # Either 400 (serializer rejects) or 201 (view force-normalised
        # to PUBLIC_REPLY). Defence-in-depth: no INTERNAL_NOTE row
        # materialises.
        self.assertNotEqual(response.status_code, 500)
        self.assertFalse(
            TicketMessage.objects.filter(
                ticket=self.ticket,
                author=self.customer_user,
                message_type=TicketMessageType.INTERNAL_NOTE,
            ).exists()
        )

    def test_staff_can_post_staff_operational(self):
        self.authenticate(self.staff_user)
        response = self._post_message(
            "Bring a ladder", TicketMessageType.STAFF_OPERATIONAL
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.content
        )
        row = TicketMessage.objects.get(pk=response.data["id"])
        self.assertEqual(
            row.message_type, TicketMessageType.STAFF_OPERATIONAL
        )
        # STAFF_OPERATIONAL is NOT moderation-hidden — visibility is
        # enforced via the queryset filter, not the is_hidden flag.
        self.assertFalse(row.is_hidden)

    def test_staff_can_post_staff_completion(self):
        self.authenticate(self.staff_user)
        response = self._post_message(
            "Done at 14:30, no damage", TicketMessageType.STAFF_COMPLETION
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.content
        )
        row = TicketMessage.objects.get(pk=response.data["id"])
        self.assertEqual(
            row.message_type, TicketMessageType.STAFF_COMPLETION
        )

    def test_customer_user_post_normalises_to_public_reply(self):
        # The view force-normalises non-provider-side authors to
        # PUBLIC_REPLY. A customer attempting any other tier ends up
        # with PUBLIC_REPLY (or 400 from the serializer, never the
        # smuggled tier).
        self.authenticate(self.customer_user)
        for tier in (
            TicketMessageType.STAFF_OPERATIONAL,
            TicketMessageType.STAFF_COMPLETION,
        ):
            response = self._post_message(f"{tier}", tier)
            self.assertNotEqual(response.status_code, 500)
            self.assertFalse(
                TicketMessage.objects.filter(
                    ticket=self.ticket,
                    author=self.customer_user,
                    message_type=tier,
                ).exists()
            )


# ---------------------------------------------------------------------------
# C. Attachment visibility + download gate per tier
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media-b7")
class AttachmentVisibilityPerTierTests(_B7Fixture):
    def setUp(self):
        super().setUp()
        self.internal_msg = _msg(
            self.ticket,
            self.manager,
            "internal",
            TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        self.staff_op_msg = _msg(
            self.ticket,
            self.manager,
            "operational",
            TicketMessageType.STAFF_OPERATIONAL,
        )
        self.staff_completion_msg = _msg(
            self.ticket,
            self.staff_user,
            "completion",
            TicketMessageType.STAFF_COMPLETION,
        )
        self.internal_att = _mk_attachment(
            self.ticket, self.manager, message=self.internal_msg
        )
        self.staff_op_att = _mk_attachment(
            self.ticket, self.manager, message=self.staff_op_msg
        )
        self.staff_completion_att = _mk_attachment(
            self.ticket, self.staff_user, message=self.staff_completion_msg
        )
        self.public_att = _mk_attachment(self.ticket, self.customer_user)

    def _list_ids(self):
        response = self.client.get(self._attachments_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data.get("results", response.data)
        return {item["id"] for item in data}

    def test_provider_management_sees_all_attachments(self):
        for actor in (self.super_admin, self.company_admin, self.manager):
            self.authenticate(actor)
            self.assertEqual(
                self._list_ids(),
                {
                    self.internal_att.id,
                    self.staff_op_att.id,
                    self.staff_completion_att.id,
                    self.public_att.id,
                },
                f"actor={actor.email}",
            )

    def test_staff_sees_public_operational_completion_only(self):
        self.authenticate(self.staff_user)
        self.assertEqual(
            self._list_ids(),
            {
                self.staff_op_att.id,
                self.staff_completion_att.id,
                self.public_att.id,
            },
        )

    def test_customer_sees_public_and_staff_completion_only(self):
        self.authenticate(self.customer_user)
        self.assertEqual(
            self._list_ids(),
            {self.staff_completion_att.id, self.public_att.id},
        )

    def test_staff_cannot_download_internal_attachment(self):
        self.authenticate(self.staff_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.internal_att)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_download_internal_attachment(self):
        self.authenticate(self.customer_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.internal_att)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_download_staff_operational_attachment(self):
        self.authenticate(self.customer_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.staff_op_att)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_download_staff_operational_attachment(self):
        self.authenticate(self.staff_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.staff_op_att)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_customer_can_download_staff_completion_attachment(self):
        self.authenticate(self.customer_user)
        response = self.client.get(
            self._attachment_download_url(
                self.ticket, self.staff_completion_att
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media-b7-write")
class AttachmentWriteValidationTests(_B7Fixture):
    def test_staff_cannot_upload_hidden_attachment(self):
        self.authenticate(self.staff_user)
        response = self.client.post(
            self._attachments_url(),
            {
                "file": SimpleUploadedFile(
                    "x.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
                "is_hidden": True,
            },
            format="multipart",
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST, response.content
        )
        self.assertFalse(
            TicketAttachment.objects.filter(
                ticket=self.ticket, uploaded_by=self.staff_user
            ).exists()
        )

    def test_provider_management_can_upload_hidden_attachment(self):
        self.authenticate(self.manager)
        response = self.client.post(
            self._attachments_url(),
            {
                "file": SimpleUploadedFile(
                    "x.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
                "is_hidden": True,
            },
            format="multipart",
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.content
        )


# ---------------------------------------------------------------------------
# D. Status-history PROVIDER_INTERNAL override redaction for STAFF
# ---------------------------------------------------------------------------
class StatusHistoryRedactionTests(_B7Fixture):
    def setUp(self):
        super().setUp()
        # Provider-driven customer-decision override row (the canonical
        # PROVIDER_INTERNAL override commentary site).
        self.override_row = TicketStatusHistory.objects.create(
            ticket=self.ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.APPROVED,
            changed_by=self.manager,
            note="Override commentary — internal cost note here",
            is_override=True,
            override_reason="Customer approved on the phone",
        )
        # Non-override provider transition (operational handoff —
        # STAFF should still see this note).
        self.handoff_row = TicketStatusHistory.objects.create(
            ticket=self.ticket,
            old_status=TicketStatus.OPEN,
            new_status=TicketStatus.IN_PROGRESS,
            changed_by=self.manager,
            note="Crew dispatched Tuesday",
            is_override=False,
            override_reason="",
        )
        # Customer-authored row (CUSTOMER_VISIBLE).
        self.customer_row = TicketStatusHistory.objects.create(
            ticket=self.ticket,
            old_status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            new_status=TicketStatus.REJECTED,
            changed_by=self.customer_user,
            note="Did not match agreed scope",
            is_override=False,
            override_reason="",
        )

    def _history_for(self, actor):
        self.authenticate(actor)
        response = self.client.get(self._ticket_detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["id"]: row for row in response.data["status_history"]}

    def test_provider_management_sees_full_override_commentary(self):
        for actor in (self.super_admin, self.company_admin, self.manager):
            rows = self._history_for(actor)
            override = rows[self.override_row.id]
            self.assertEqual(
                override["note"],
                "Override commentary — internal cost note here",
            )
            self.assertEqual(
                override["override_reason"],
                "Customer approved on the phone",
            )

    def test_staff_cannot_see_override_commentary(self):
        rows = self._history_for(self.staff_user)
        override = rows[self.override_row.id]
        # B7 — provider override commentary is redacted for STAFF.
        self.assertEqual(override["note"], "")
        self.assertEqual(override["override_reason"], "")

    def test_staff_still_sees_non_override_provider_notes(self):
        # Operational handoff context remains visible to STAFF.
        rows = self._history_for(self.staff_user)
        handoff = rows[self.handoff_row.id]
        self.assertEqual(handoff["note"], "Crew dispatched Tuesday")

    def test_staff_sees_customer_authored_notes(self):
        rows = self._history_for(self.staff_user)
        cust = rows[self.customer_row.id]
        self.assertEqual(cust["note"], "Did not match agreed scope")

    def test_customer_redaction_unchanged_from_b1(self):
        rows = self._history_for(self.customer_user)
        # Customer-authored note still visible to customer.
        self.assertEqual(
            rows[self.customer_row.id]["note"], "Did not match agreed scope"
        )
        # Provider notes still redacted from customer.
        self.assertEqual(rows[self.override_row.id]["note"], "")
        self.assertEqual(rows[self.override_row.id]["override_reason"], "")
        self.assertEqual(rows[self.handoff_row.id]["note"], "")


# ---------------------------------------------------------------------------
# E. Staff completion-evidence rule respects the four-tier taxonomy
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media-b7-evidence")
class CompletionEvidenceRuleTests(_B7Fixture):
    def setUp(self):
        super().setUp()
        # Sprint 25C / B1: STAFF needs an explicit assignment row to
        # drive the IN_PROGRESS → WAITING_MANAGER_REVIEW transition.
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff_user
        )

    def _set_in_progress(self):
        self.ticket.status = TicketStatus.IN_PROGRESS
        self.ticket.save(update_fields=["status"])

    def test_staff_operational_attachment_alone_does_not_satisfy_evidence(self):
        # B7 — STAFF_OPERATIONAL is not customer-visible, so an
        # attachment on a STAFF_OPERATIONAL message cannot satisfy the
        # "customer-visible evidence" rule.
        from tickets.state_machine import (
            TransitionError,
            apply_transition,
        )

        self._set_in_progress()
        op_msg = _msg(
            self.ticket,
            self.staff_user,
            "Bring ladder",
            TicketMessageType.STAFF_OPERATIONAL,
        )
        _mk_attachment(self.ticket, self.staff_user, message=op_msg)
        with self.assertRaises(TransitionError) as ctx:
            apply_transition(
                self.ticket,
                self.staff_user,
                TicketStatus.WAITING_MANAGER_REVIEW,
                note="",
            )
        self.assertEqual(ctx.exception.code, "completion_evidence_required")

    def test_staff_completion_attachment_alone_satisfies_evidence(self):
        # B7 — STAFF_COMPLETION is customer-visible; an attachment on
        # one IS valid evidence.
        from tickets.state_machine import apply_transition

        self._set_in_progress()
        completion_msg = _msg(
            self.ticket,
            self.staff_user,
            "Completed",
            TicketMessageType.STAFF_COMPLETION,
        )
        _mk_attachment(
            self.ticket, self.staff_user, message=completion_msg
        )
        apply_transition(
            self.ticket,
            self.staff_user,
            TicketStatus.WAITING_MANAGER_REVIEW,
            note="",
        )
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.WAITING_MANAGER_REVIEW)
        )

    def test_public_reply_attachment_alone_satisfies_evidence(self):
        # P0/B1 baseline preserved — PUBLIC_REPLY attachment counts.
        from tickets.state_machine import apply_transition

        self._set_in_progress()
        _mk_attachment(self.ticket, self.staff_user)
        apply_transition(
            self.ticket,
            self.staff_user,
            TicketStatus.WAITING_MANAGER_REVIEW,
            note="",
        )
        self.ticket.refresh_from_db()
        self.assertEqual(
            str(self.ticket.status), str(TicketStatus.WAITING_MANAGER_REVIEW)
        )


# ---------------------------------------------------------------------------
# F. URL-smuggling regression — direct URL attempts cannot leak
#    PROVIDER_INTERNAL content.
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media-b7-smuggle")
class UrlSmugglingRegressionTests(_B7Fixture):
    def setUp(self):
        super().setUp()
        self.internal_msg = _msg(
            self.ticket,
            self.manager,
            "Cost is EUR 120 / margin low",
            TicketMessageType.INTERNAL_NOTE,
            is_hidden=True,
        )
        self.staff_op_msg = _msg(
            self.ticket,
            self.manager,
            "Bring ladder",
            TicketMessageType.STAFF_OPERATIONAL,
        )
        self.internal_att = _mk_attachment(
            self.ticket, self.manager, message=self.internal_msg
        )
        self.staff_op_att = _mk_attachment(
            self.ticket, self.manager, message=self.staff_op_msg
        )

    def test_staff_message_list_does_not_leak_internal_body(self):
        self.authenticate(self.staff_user)
        response = self.client.get(self._messages_url())
        body = response.content.decode("utf-8")
        self.assertNotIn("Cost is EUR 120", body)
        self.assertNotIn("margin low", body)

    def test_customer_message_list_does_not_leak_internal_or_operational(self):
        self.authenticate(self.customer_user)
        response = self.client.get(self._messages_url())
        body = response.content.decode("utf-8")
        self.assertNotIn("Cost is EUR 120", body)
        self.assertNotIn("Bring ladder", body)

    def test_staff_attachment_download_internal_returns_403(self):
        self.authenticate(self.staff_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.internal_att)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_attachment_download_staff_operational_returns_403(self):
        self.authenticate(self.customer_user)
        response = self.client.get(
            self._attachment_download_url(self.ticket, self.staff_op_att)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Helper-role sanity
# ---------------------------------------------------------------------------
class RoleHelperSanityTests(_B7Fixture):
    def test_is_provider_management_role_excludes_staff_and_customer(self):
        self.assertTrue(is_provider_management_role(self.super_admin))
        self.assertTrue(is_provider_management_role(self.company_admin))
        self.assertTrue(is_provider_management_role(self.manager))
        self.assertFalse(is_provider_management_role(self.staff_user))
        self.assertFalse(is_provider_management_role(self.customer_user))

    def test_is_staff_role_still_includes_staff(self):
        # B7 keeps is_staff_role intact for the operational-evidence
        # / first-response / status-change branches that still need
        # "is the actor on the OSIUS side?".
        self.assertTrue(is_staff_role(self.staff_user))
        self.assertTrue(is_staff_role(self.manager))
        self.assertFalse(is_staff_role(self.customer_user))
