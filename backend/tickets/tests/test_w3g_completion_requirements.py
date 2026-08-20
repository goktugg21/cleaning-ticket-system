"""W3-G — the completion gate reads the job's own two flags.

Plan §2.3. W2-D stored `file_upload_required` and
`completion_notes_required` on the extra work, both defaulting False,
and left enforcement to this sprint. What is worth testing is not that
a boolean is read but the four things that could make the gate lie:

  * the FOUR combinations, on BOTH gates, because the rule binds two
    surfaces and a rule that bound only one could be walked around by
    using the other;
  * the no-extra-work fallback, which must be EXACTLY what it was
    before this sprint — a plain ticket's requirement is not this
    sprint's to change;
  * the message, which has to name what is missing now that "a note or
    a photo" is true of only some jobs;
  * the read-only requirements endpoint the dialog asks, including who
    may ask it.

The two gates deliberately read DIFFERENT evidence pools — the slot's
own linked attachments vs the ticket's customer-visible ones — so each
is tested against its own pool rather than one being assumed from the
other.
"""
from __future__ import annotations

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from test_utils import TenantFixtureMixin
from tickets.completion_requirements import (
    LEGACY_NOTE_OR_PHOTO,
    SOURCE_DEFAULT,
    SOURCE_EXTRA_WORK,
    message_for,
    missing_evidence,
    requirements_for_ticket,
)
from tickets.models import (
    StaffAssignmentSlotStatus,
    TicketAttachment,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.state_machine import TransitionError, apply_transition
from tickets.tests.test_sprint25c_completion_evidence import _wire_staff_actor


_TMP_MEDIA = tempfile.mkdtemp(prefix="w3g-media-")

#: The four combinations, once, so a test cannot cover three and look
#: like it covered four.
COMBINATIONS = (
    # (file_upload_required, completion_notes_required, expected missing set
    #  when the worker supplies nothing at all)
    (False, False, ()),
    (True, False, ("file",)),
    (False, True, ("note",)),
    (True, True, ("note", "file")),
)


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class _W3GFixture(TenantFixtureMixin, APITestCase):
    """A ticket with a slot, plus a second ticket born from an extra
    work so the two branches can be compared side by side."""

    def setUp(self):
        super().setUp()
        self.staff = self.make_user("staff-w3g@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        # `self.ticket` from the fixture has NO extra work — the
        # fallback branch.
        self.plain_slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.manager
        )
        # A second ticket that DID come from an extra work.
        self.extra_work = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Deep clean the stairwell",
            description="customer-visible description",
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
        )
        self.ew_ticket = self.ticket.__class__.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.manager,
            title="Spawned operational ticket",
            description="op ticket",
            extra_work_request=self.extra_work,
        )
        self.ew_slot = TicketStaffAssignment.objects.create(
            ticket=self.ew_ticket, user=self.staff, assigned_by=self.manager
        )

    # ---- helpers --------------------------------------------------------
    def set_flags(self, *, file_required, notes_required):
        self.extra_work.file_upload_required = file_required
        self.extra_work.completion_notes_required = notes_required
        self.extra_work.save(
            update_fields=["file_upload_required", "completion_notes_required"]
        )

    def complete(self, slot, *, note=""):
        return self.client.patch(
            f"/api/tickets/{slot.ticket_id}/staff-assignments/{slot.id}/",
            {
                "slot_status": StaffAssignmentSlotStatus.COMPLETED,
                "completion_note": note,
            },
            format="json",
        )

    def link_file(self, slot, *, name="proof.pdf", mime="application/pdf"):
        """An attachment linked to the SLOT, bypassing the upload
        endpoint's own mime/extension pairing check so the gate can be
        tested against a non-photo file directly."""
        return TicketAttachment.objects.create(
            ticket=slot.ticket,
            staff_assignment=slot,
            uploaded_by=self.staff,
            file=SimpleUploadedFile(name, b"%PDF-1.4", content_type=mime),
            original_filename=name,
            mime_type=mime,
            file_size=8,
        )

    def link_photo(self, slot):
        return TicketAttachment.objects.create(
            ticket=slot.ticket,
            staff_assignment=slot,
            uploaded_by=self.staff,
            file=SimpleUploadedFile(
                "ev.jpg", b"\xff\xd8\xff", content_type="image/jpeg"
            ),
            original_filename="ev.jpg",
            mime_type="image/jpeg",
            file_size=3,
        )


class RuleResolutionTests(_W3GFixture):
    def test_no_extra_work_is_the_legacy_rule(self):
        reqs = requirements_for_ticket(self.ticket)
        self.assertEqual(reqs, LEGACY_NOTE_OR_PHOTO)
        self.assertEqual(reqs.source, SOURCE_DEFAULT)
        self.assertTrue(reqs.either_required)

    def test_extra_work_supplies_both_flags_independently(self):
        for file_required, notes_required, _missing in COMBINATIONS:
            with self.subTest(file=file_required, notes=notes_required):
                self.set_flags(
                    file_required=file_required, notes_required=notes_required
                )
                self.ew_ticket.refresh_from_db()
                reqs = requirements_for_ticket(self.ew_ticket)
                self.assertEqual(reqs.source, SOURCE_EXTRA_WORK)
                self.assertFalse(reqs.either_required)
                self.assertEqual(reqs.file_required, file_required)
                self.assertEqual(reqs.note_required, notes_required)

    def test_missing_set_for_every_combination(self):
        for file_required, notes_required, expected in COMBINATIONS:
            with self.subTest(file=file_required, notes=notes_required):
                self.set_flags(
                    file_required=file_required, notes_required=notes_required
                )
                self.ew_ticket.refresh_from_db()
                reqs = requirements_for_ticket(self.ew_ticket)
                self.assertEqual(
                    missing_evidence(reqs, has_note=False, has_file=False),
                    expected,
                )
                # Supplying everything always clears it.
                self.assertEqual(
                    missing_evidence(reqs, has_note=True, has_file=True), ()
                )

    def test_every_message_names_what_is_missing(self):
        # A message that did not mention the missing thing would be the
        # defect this sprint exists to remove.
        self.assertIn("note", message_for(("note",)).lower())
        self.assertIn("file", message_for(("file",)).lower())
        both = message_for(("note", "file")).lower()
        self.assertIn("note", both)
        self.assertIn("file", both)
        self.assertIn("photo", message_for(("either",)).lower())
        self.assertEqual(message_for(()), "")


class SlotGateFlagTests(_W3GFixture):
    """The per-slot gate, over the four combinations. Evidence is what
    is linked to THIS slot."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.staff)

    def test_both_off_requires_nothing(self):
        self.set_flags(file_required=False, notes_required=False)
        resp = self.complete(self.ew_slot)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ew_slot.refresh_from_db()
        self.assertEqual(
            self.ew_slot.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )

    def test_file_only_refuses_a_note_and_accepts_a_file(self):
        self.set_flags(file_required=True, notes_required=False)
        refused = self.complete(self.ew_slot, note="All done.")
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            refused.data["completion_note"][0].code,
            "completion_evidence_required",
        )
        self.assertIn("file", str(refused.data["completion_note"][0]).lower())
        self.link_file(self.ew_slot)
        ok = self.complete(self.ew_slot, note="All done.")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

    def test_note_only_refuses_a_file_and_accepts_a_note(self):
        self.set_flags(file_required=False, notes_required=True)
        self.link_photo(self.ew_slot)
        refused = self.complete(self.ew_slot)
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("note", str(refused.data["completion_note"][0]).lower())
        ok = self.complete(self.ew_slot, note="Stairwell done, 3 hours.")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

    def test_both_on_requires_both(self):
        self.set_flags(file_required=True, notes_required=True)
        self.assertEqual(
            self.complete(self.ew_slot, note="Done.").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.link_photo(self.ew_slot)
        self.assertEqual(
            self.complete(self.ew_slot).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        ok = self.complete(self.ew_slot, note="Done.")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

    def test_a_pdf_satisfies_file_required(self):
        # `file_upload_required` says FILE. A PDF is a file. The legacy
        # arm's photo-only strictness is a different question and is
        # asserted below, unchanged.
        self.set_flags(file_required=True, notes_required=False)
        self.link_file(self.ew_slot, name="signoff.pdf")
        ok = self.complete(self.ew_slot)
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

    def test_a_sibling_slots_photo_is_not_this_slots_evidence(self):
        # The rule became configurable; the evidence pool did not. A
        # slot is one worker's one visit.
        self.set_flags(file_required=True, notes_required=False)
        other_slot = TicketStaffAssignment.objects.create(
            ticket=self.ew_ticket, user=self.staff, assigned_by=self.manager
        )
        self.link_photo(other_slot)
        refused = self.complete(self.ew_slot)
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)


class SlotGateNoExtraWorkTests(_W3GFixture):
    """A plain ticket keeps EXACTLY the rule it has always had. This is
    the owner's decision, recorded as tests so a later sprint cannot
    drift it by accident."""

    def setUp(self):
        super().setUp()
        self.authenticate(self.staff)

    def test_nothing_is_still_refused(self):
        resp = self.complete(self.plain_slot)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["completion_note"][0].code,
            "completion_evidence_required",
        )

    def test_a_note_alone_is_enough(self):
        resp = self.complete(self.plain_slot, note="Bins emptied.")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_a_photo_alone_is_enough(self):
        self.link_photo(self.plain_slot)
        resp = self.complete(self.plain_slot)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_a_pdf_alone_is_still_not_enough(self):
        # Sprint 12's photo-only reading of the legacy arm, unchanged.
        self.link_file(self.plain_slot)
        resp = self.complete(self.plain_slot)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class TicketGateFlagTests(_W3GFixture):
    """The ticket-level STAFF completion transition — the one that makes
    work billable. Evidence here is the TICKET's customer-visible
    attachments, not a slot's."""

    def setUp(self):
        super().setUp()
        _wire_staff_actor(self, self.ew_ticket)
        self.ew_ticket = apply_transition(
            self.ew_ticket, self.manager, TicketStatus.IN_PROGRESS
        )

    def send_for_approval(self, note=""):
        return apply_transition(
            self.ew_ticket,
            self.staff_user,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
            note=note,
        )

    def ticket_attachment(self):
        return TicketAttachment.objects.create(
            ticket=self.ew_ticket,
            uploaded_by=self.staff_user,
            file=SimpleUploadedFile(
                "ev.jpg", b"\xff\xd8\xff", content_type="image/jpeg"
            ),
            original_filename="ev.jpg",
            mime_type="image/jpeg",
            file_size=3,
        )

    def test_both_off_requires_nothing(self):
        self.set_flags(file_required=False, notes_required=False)
        result = self.send_for_approval()
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_note_required_refuses_an_attachment_alone(self):
        self.set_flags(file_required=False, notes_required=True)
        self.ticket_attachment()
        with self.assertRaises(TransitionError) as ctx:
            self.send_for_approval()
        self.assertEqual(ctx.exception.code, "completion_evidence_required")
        self.assertIn("note", str(ctx.exception).lower())
        result = self.send_for_approval(note="Stairwell done.")
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_file_required_refuses_a_note_alone(self):
        self.set_flags(file_required=True, notes_required=False)
        with self.assertRaises(TransitionError) as ctx:
            self.send_for_approval(note="Stairwell done.")
        self.assertIn("file", str(ctx.exception).lower())
        self.ticket_attachment()
        result = self.send_for_approval(note="Stairwell done.")
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_both_on_requires_both(self):
        self.set_flags(file_required=True, notes_required=True)
        with self.assertRaises(TransitionError):
            self.send_for_approval(note="Done.")
        self.ticket_attachment()
        with self.assertRaises(TransitionError):
            self.send_for_approval()
        result = self.send_for_approval(note="Done.")
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )

    def test_a_manager_still_bypasses_the_gate(self):
        # B1 is unchanged by this sprint: WHO the rule applies to stays
        # STAFF-only. Worth an assertion because it is the one way a
        # configured requirement can still be skipped, and the owner
        # should be able to see that we knew.
        self.set_flags(file_required=True, notes_required=True)
        result = apply_transition(
            self.ew_ticket,
            self.manager,
            TicketStatus.WAITING_CUSTOMER_APPROVAL,
        )
        self.assertEqual(
            result.status, TicketStatus.WAITING_CUSTOMER_APPROVAL
        )


class RequirementsEndpointTests(_W3GFixture):
    def url(self, slot):
        return (
            f"/api/tickets/{slot.ticket_id}/staff-assignments/"
            f"{slot.id}/completion-requirements/"
        )

    def test_staff_reads_their_own_slot(self):
        self.set_flags(file_required=True, notes_required=False)
        self.authenticate(self.staff)
        resp = self.client.get(self.url(self.ew_slot))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.data,
            {
                "note_required": False,
                "file_required": True,
                "either_required": False,
                "source": "extra_work",
            },
        )

    def test_plain_ticket_reports_the_legacy_rule(self):
        self.authenticate(self.staff)
        resp = self.client.get(self.url(self.plain_slot))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["source"], "default")
        self.assertTrue(resp.data["either_required"])

    def test_manager_may_read(self):
        self.authenticate(self.manager)
        resp = self.client.get(self.url(self.ew_slot))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_another_staffs_slot_is_refused(self):
        other = self.make_user("staff-w3g-other@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=other)
        BuildingStaffVisibility.objects.create(
            user=other, building=self.building
        )
        self.authenticate(other)
        resp = self.client.get(self.url(self.ew_slot))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_is_refused(self):
        self.authenticate(self.customer_user)
        resp = self.client.get(self.url(self.ew_slot))
        self.assertIn(
            resp.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )

    def test_cross_tenant_actor_gets_nothing(self):
        self.authenticate(self.other_manager)
        resp = self.client.get(self.url(self.ew_slot))
        self.assertIn(
            resp.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )
