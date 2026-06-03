"""Sprint 12 — staff slot completion requires evidence (note OR photo).

Backend enforcement of Ramazan's rule: when a staff member marks a job
done they MUST leave a note or a photo; "Start/Stop" is gone. The rule
lives on the per-staff dated SLOT (TicketStaffAssignment), which until now
accepted slot_status=COMPLETED with no note and no photo. A photo can now
be linked to a specific slot via TicketAttachment.staff_assignment, with
scope rules (same ticket; STAFF only their own slot; customers never).

The slot completion does NOT drive the ticket state machine (unchanged) —
this is additive operational evidence on the slot.
"""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    StaffAssignmentSlotStatus,
    TicketAttachment,
    TicketStaffAssignment,
)


@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media")
class SlotCompletionEvidenceTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        # STAFF with visibility on Building A + a slot on self.ticket.
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        self.slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.manager
        )

        # A second STAFF + slot (for the "not your slot" test).
        self.staff2 = self.make_user("staff-b@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff2)
        BuildingStaffVisibility.objects.create(
            user=self.staff2, building=self.building
        )
        self.slot2 = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff2, assigned_by=self.manager
        )

        # A slot on a DIFFERENT ticket (cross-ticket rejection).
        self.cross_slot = TicketStaffAssignment.objects.create(
            ticket=self.other_ticket,
            user=self.staff2,
            assigned_by=self.other_manager,
        )

    # ---- helpers ----------------------------------------------------------
    def upload(self, *, ticket=None, name="ev.jpg", content=b"\xff\xd8\xff\xe0",
               content_type="image/jpeg", **extra):
        ticket = ticket or self.ticket
        data = {
            "file": SimpleUploadedFile(name, content, content_type=content_type),
            **extra,
        }
        return self.client.post(
            f"/api/tickets/{ticket.id}/attachments/", data, format="multipart"
        )

    def patch_slot(self, *, ticket=None, user=None, **body):
        ticket = ticket or self.ticket
        user = user or self.staff
        return self.client.patch(
            f"/api/tickets/{ticket.id}/staff-assignments/{user.id}/",
            body,
            format="json",
        )

    # ---- completion evidence enforcement ---------------------------------
    def test_completed_without_note_or_photo_rejected(self):
        self.authenticate(self.staff)
        resp = self.patch_slot(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["completion_note"][0].code, "completion_evidence_required"
        )
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.slot_status, StaffAssignmentSlotStatus.ASSIGNED)

    def test_completed_with_note_ok(self):
        self.authenticate(self.staff)
        resp = self.patch_slot(
            slot_status=StaffAssignmentSlotStatus.COMPLETED,
            completion_note="Done; bins emptied.",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.slot_status, StaffAssignmentSlotStatus.COMPLETED)
        self.assertIsNotNone(self.slot.completed_at)
        self.assertEqual(self.slot.completed_by_id, self.staff.id)

    def test_completed_with_linked_photo_and_blank_note_ok(self):
        self.authenticate(self.staff)
        up = self.upload(staff_assignment_id=self.slot.id)
        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        self.assertEqual(
            TicketAttachment.objects.get(id=up.data["id"]).staff_assignment_id,
            self.slot.id,
        )
        resp = self.patch_slot(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.slot_status, StaffAssignmentSlotStatus.COMPLETED)

    def test_linked_pdf_does_not_satisfy_photo_evidence(self):
        self.authenticate(self.staff)
        up = self.upload(
            name="proof.pdf",
            content=b"%PDF-1.4",
            content_type="application/pdf",
            staff_assignment_id=self.slot.id,
        )
        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        resp = self.patch_slot(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["completion_note"][0].code, "completion_evidence_required"
        )

    def test_completed_with_linked_png_photo_ok(self):
        # A genuine PNG (image MIME + image extension) is valid evidence.
        self.authenticate(self.staff)
        up = self.upload(
            name="ev.png",
            content=b"\x89PNG\r\n\x1a\n",
            content_type="image/png",
            staff_assignment_id=self.slot.id,
        )
        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        resp = self.patch_slot(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    # ---- P2 #2: extension/MIME pairing + spoof-proof photo evidence ------
    def test_upload_pdf_with_image_mime_rejected(self):
        # A file named proof.pdf MUST NOT be uploadable as image/jpeg — the
        # extension and content type must agree, or a fake photo could be
        # stored and later satisfy the completion-photo gate.
        self.authenticate(self.staff)
        up = self.upload(
            name="proof.pdf",
            content=b"%PDF-1.4",
            content_type="image/jpeg",
            staff_assignment_id=self.slot.id,
        )
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(up.data["file"][0].code, "invalid_file_mime_pair")

    def test_upload_jpg_with_pdf_mime_rejected(self):
        self.authenticate(self.staff)
        up = self.upload(
            name="photo.jpg",
            content=b"\xff\xd8\xff\xe0",
            content_type="application/pdf",
        )
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(up.data["file"][0].code, "invalid_file_mime_pair")

    def test_historical_bad_pdf_row_does_not_satisfy_photo_evidence(self):
        # Simulate historical bad data that bypassed validate_file: a row
        # whose filename is proof.pdf but whose stored mime_type is
        # image/jpeg, linked to the slot. A MIME-only check would wrongly
        # accept it; the extension (.pdf) must disqualify it.
        TicketAttachment.objects.create(
            ticket=self.ticket,
            staff_assignment=self.slot,
            uploaded_by=self.staff,
            file=SimpleUploadedFile(
                "proof.pdf", b"%PDF-1.4", content_type="image/jpeg"
            ),
            original_filename="proof.pdf",
            mime_type="image/jpeg",
            file_size=8,
            is_hidden=False,
        )
        self.authenticate(self.staff)
        resp = self.patch_slot(slot_status=StaffAssignmentSlotStatus.COMPLETED)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["completion_note"][0].code, "completion_evidence_required"
        )

    # ---- evidence-link scope rules ---------------------------------------
    def test_staff_cannot_link_to_another_staffs_slot(self):
        self.authenticate(self.staff)
        up = self.upload(staff_assignment_id=self.slot2.id)
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            up.data["staff_assignment_id"][0].code, "slot_not_owned"
        )

    def test_cross_ticket_slot_link_rejected(self):
        # staff uploads to self.ticket but points at a slot on other_ticket.
        self.authenticate(self.staff)
        up = self.upload(staff_assignment_id=self.cross_slot.id)
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            up.data["staff_assignment_id"][0].code, "slot_ticket_mismatch"
        )

    def test_manager_can_link_evidence_to_scoped_slot(self):
        self.authenticate(self.company_admin)
        up = self.upload(staff_assignment_id=self.slot.id)
        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        self.assertEqual(
            TicketAttachment.objects.get(id=up.data["id"]).staff_assignment_id,
            self.slot.id,
        )

    def test_customer_cannot_link_evidence_to_staff_slot(self):
        self.authenticate(self.customer_user)
        up = self.upload(staff_assignment_id=self.slot.id)
        self.assertEqual(up.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            up.data["staff_assignment_id"][0].code, "slot_link_forbidden"
        )

    def test_plain_upload_without_slot_still_works(self):
        # Regression: an attachment with no staff_assignment_id is unchanged.
        self.authenticate(self.customer_user)
        up = self.upload()
        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        self.assertIsNone(
            TicketAttachment.objects.get(id=up.data["id"]).staff_assignment_id
        )

    # ---- preserved behavior ----------------------------------------------
    def test_unable_to_complete_without_reason_still_rejected(self):
        self.authenticate(self.staff)
        resp = self.patch_slot(
            slot_status=StaffAssignmentSlotStatus.UNABLE_TO_COMPLETE
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["unable_to_complete_reason"][0].code,
            "slot_unable_reason_required",
        )
