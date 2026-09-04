"""
Sprint 191 §2.5 — the photo pool: visibility is its own axis.

What this module pins:

  1. DEFAULTS. A staff upload lands INTERNAL. A customer's own upload
     lands CUSTOMER (hiding it from the person who uploaded it would be
     a bug, not a privacy win). The per-work
     `Ticket.staff_uploads_customer_visible` switch — and only that
     switch — makes a staff upload customer-visible immediately.
  2. THE CUSTOMER WALL, on BOTH read paths. The list endpoint and the
     download endpoint refuse the same rows; a wall enforced on one of
     them is decorative.
  3. THE PROMOTE ACTION. Provider management only. STAFF cannot publish
     its own photo, a customer cannot publish anything, and the flip
     writes an AuditLog row.
  4. TENANT SCOPING (the P0 surface). No customer sees another
     customer's photo; no manager promotes across a tenant boundary; an
     attachment id from another ticket 404s on this ticket's URL.
  5. THE COMPLETION-EVIDENCE GATE IS UNCHANGED. This is the one that
     could have gone wrong quietly: the gates count `is_hidden=False`
     rows, and `visibility` is a different column. A photo a worker
     uploaded as proof still satisfies both the per-slot gate and the
     ticket-level gate while it is INTERNAL. The customer not seeing it
     yet does not mean the work did not happen.
  6. PHASE IS NOT VISIBILITY. Both directions: a BEFORE photo can be
     customer-visible and an AFTER photo can be internal. Labelling
     publishes nothing (this is precisely the reference system's bug).
"""
from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import BuildingStaffVisibility
from test_utils import TenantFixtureMixin
from tickets.models import (
    AttachmentPhase,
    AttachmentVisibility,
    StaffAssignmentSlotStatus,
    TicketAttachment,
    TicketMessage,
    TicketMessageType,
    TicketStaffAssignment,
    TicketStatus,
)
from tickets.state_machine import _ticket_has_visible_attachment


JPEG = b"\xff\xd8\xff\xe0"


@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media")
class _VisibilityFixture(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.staff = self.make_user("staff-a@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=self.staff)
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )
        self.slot = TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.manager
        )

    # ---- helpers ---------------------------------------------------------
    def upload(self, *, ticket=None, name="proof.jpg", content=JPEG,
               content_type="image/jpeg", **extra):
        ticket = ticket or self.ticket
        data = {
            "file": SimpleUploadedFile(name, content, content_type=content_type),
            **extra,
        }
        return self.client.post(
            f"/api/tickets/{ticket.id}/attachments/", data, format="multipart"
        )

    def make_attachment(self, *, ticket=None, uploaded_by=None, **extra):
        """A row written straight to the DB, for the read-side tests that
        need a given starting state rather than a given upload path."""
        return TicketAttachment.objects.create(
            ticket=ticket or self.ticket,
            uploaded_by=uploaded_by or self.staff,
            file=SimpleUploadedFile("proof.jpg", JPEG, content_type="image/jpeg"),
            original_filename="proof.jpg",
            mime_type="image/jpeg",
            file_size=len(JPEG),
            **extra,
        )

    def list_attachments(self, ticket=None):
        ticket = ticket or self.ticket
        return self.client.get(f"/api/tickets/{ticket.id}/attachments/")

    def download(self, attachment, ticket=None):
        ticket = ticket or self.ticket
        return self.client.get(
            f"/api/tickets/{ticket.id}/attachments/{attachment.id}/download/"
        )

    def set_visibility(self, attachment, value, ticket=None):
        ticket = ticket or self.ticket
        return self.client.patch(
            f"/api/tickets/{ticket.id}/attachments/{attachment.id}/visibility/",
            {"visibility": value},
            format="json",
        )

    def set_policy(self, value, ticket=None):
        ticket = ticket or self.ticket
        return self.client.patch(
            f"/api/tickets/{ticket.id}/attachment-visibility-policy/",
            {"staff_uploads_customer_visible": value},
            format="json",
        )


class UploadDefaultsTests(_VisibilityFixture):
    def test_staff_upload_lands_internal(self):
        self.authenticate(self.staff)
        resp = self.upload()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["visibility"], AttachmentVisibility.INTERNAL)
        self.assertEqual(
            TicketAttachment.objects.get(id=resp.data["id"]).visibility,
            AttachmentVisibility.INTERNAL,
        )

    def test_staff_upload_is_customer_visible_when_the_work_says_so(self):
        self.ticket.staff_uploads_customer_visible = True
        self.ticket.save(update_fields=["staff_uploads_customer_visible"])

        self.authenticate(self.staff)
        resp = self.upload()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["visibility"], AttachmentVisibility.CUSTOMER)

    def test_customer_own_upload_is_customer_visible(self):
        self.authenticate(self.customer_user)
        resp = self.upload()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["visibility"], AttachmentVisibility.CUSTOMER)
        # And they can still read back what they just uploaded.
        self.assertIn(resp.data["id"], self.response_ids(self.list_attachments()))

    def test_manager_upload_defaults_internal_but_can_be_chosen(self):
        self.authenticate(self.manager)
        default = self.upload()
        chosen = self.upload(visibility=AttachmentVisibility.CUSTOMER)

        self.assertEqual(default.data["visibility"], AttachmentVisibility.INTERNAL)
        self.assertEqual(chosen.data["visibility"], AttachmentVisibility.CUSTOMER)

    def test_staff_cannot_choose_visibility_at_upload(self):
        self.authenticate(self.staff)
        resp = self.upload(visibility=AttachmentVisibility.CUSTOMER)

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["visibility"][0].code, "visibility_forbidden")

    def test_customer_cannot_choose_visibility_at_upload(self):
        self.authenticate(self.customer_user)
        resp = self.upload(visibility=AttachmentVisibility.INTERNAL)

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["visibility"][0].code, "visibility_forbidden")


class CustomerWallTests(_VisibilityFixture):
    def setUp(self):
        super().setUp()
        self.internal = self.make_attachment(
            visibility=AttachmentVisibility.INTERNAL
        )
        self.released = self.make_attachment(
            visibility=AttachmentVisibility.CUSTOMER
        )

    def test_customer_list_shows_only_released_rows(self):
        self.authenticate(self.customer_user)
        resp = self.list_attachments()

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self.response_ids(resp), {self.released.id})

    def test_customer_download_of_an_internal_row_is_refused(self):
        self.authenticate(self.customer_user)

        self.assertEqual(
            self.download(self.internal).status_code, status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.download(self.released).status_code, status.HTTP_200_OK
        )

    def test_the_worker_keeps_seeing_their_own_internal_photo(self):
        self.authenticate(self.staff)
        resp = self.list_attachments()

        self.assertEqual(
            self.response_ids(resp), {self.internal.id, self.released.id}
        )
        self.assertEqual(
            self.download(self.internal).status_code, status.HTTP_200_OK
        )

    def test_provider_management_sees_everything(self):
        for actor in (self.manager, self.company_admin, self.super_admin):
            with self.subTest(actor=actor.email):
                self.authenticate(actor)
                self.assertEqual(
                    self.response_ids(self.list_attachments()),
                    {self.internal.id, self.released.id},
                )


class PromoteActionTests(_VisibilityFixture):
    def setUp(self):
        super().setUp()
        self.attachment = self.make_attachment(
            visibility=AttachmentVisibility.INTERNAL
        )

    def test_manager_promotes_and_the_customer_can_then_see_it(self):
        self.authenticate(self.manager)
        resp = self.set_visibility(
            self.attachment, AttachmentVisibility.CUSTOMER
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["visibility"], AttachmentVisibility.CUSTOMER)
        self.attachment.refresh_from_db()
        self.assertEqual(
            self.attachment.visibility, AttachmentVisibility.CUSTOMER
        )

        self.authenticate(self.customer_user)
        self.assertIn(
            self.attachment.id, self.response_ids(self.list_attachments())
        )
        self.assertEqual(
            self.download(self.attachment).status_code, status.HTTP_200_OK
        )

    def test_a_promote_can_be_taken_back(self):
        self.authenticate(self.company_admin)
        self.set_visibility(self.attachment, AttachmentVisibility.CUSTOMER)
        resp = self.set_visibility(
            self.attachment, AttachmentVisibility.INTERNAL
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.authenticate(self.customer_user)
        self.assertEqual(self.response_ids(self.list_attachments()), set())

    def test_staff_cannot_promote_its_own_photo(self):
        self.authenticate(self.staff)
        resp = self.set_visibility(
            self.attachment, AttachmentVisibility.CUSTOMER
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "attachment_visibility_forbidden")
        self.attachment.refresh_from_db()
        self.assertEqual(
            self.attachment.visibility, AttachmentVisibility.INTERNAL
        )

    def test_customer_cannot_promote(self):
        self.authenticate(self.customer_user)
        resp = self.set_visibility(
            self.attachment, AttachmentVisibility.CUSTOMER
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "attachment_visibility_forbidden")

    def test_a_hidden_row_cannot_be_released(self):
        hidden = self.make_attachment(
            uploaded_by=self.manager,
            is_hidden=True,
            visibility=AttachmentVisibility.INTERNAL,
        )
        self.authenticate(self.manager)
        resp = self.set_visibility(hidden, AttachmentVisibility.CUSTOMER)

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "attachment_visibility_conflict")
        hidden.refresh_from_db()
        self.assertEqual(hidden.visibility, AttachmentVisibility.INTERNAL)

    def test_a_row_on_an_internal_note_cannot_be_released(self):
        note = TicketMessage.objects.create(
            ticket=self.ticket,
            author=self.manager,
            message="internal",
            message_type=TicketMessageType.INTERNAL_NOTE,
        )
        attachment = self.make_attachment(
            uploaded_by=self.manager,
            message=note,
            visibility=AttachmentVisibility.INTERNAL,
        )
        self.authenticate(self.manager)
        resp = self.set_visibility(attachment, AttachmentVisibility.CUSTOMER)

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "attachment_visibility_conflict")

    def test_an_unknown_visibility_value_is_refused(self):
        self.authenticate(self.manager)
        resp = self.client.patch(
            f"/api/tickets/{self.ticket.id}/attachments/"
            f"{self.attachment.id}/visibility/",
            {"visibility": "EVERYONE"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_promote_is_audited(self):
        self.authenticate(self.manager)
        self.set_visibility(self.attachment, AttachmentVisibility.CUSTOMER)

        row = AuditLog.objects.filter(
            target_model="tickets.TicketAttachment",
            target_id=self.attachment.id,
            action=AuditAction.UPDATE,
        ).latest("id")

        self.assertEqual(row.actor_id, self.manager.id)
        self.assertEqual(
            row.changes["visibility"],
            {
                "before": AttachmentVisibility.INTERNAL,
                "after": AttachmentVisibility.CUSTOMER,
            },
        )


class PromoteTenantScopingTests(_VisibilityFixture):
    """The P0 surface: a promote must never cross a tenant boundary and a
    customer must never reach another customer's photo."""

    def setUp(self):
        super().setUp()
        self.attachment = self.make_attachment(
            visibility=AttachmentVisibility.INTERNAL
        )
        self.other_attachment = TicketAttachment.objects.create(
            ticket=self.other_ticket,
            uploaded_by=self.other_manager,
            file=SimpleUploadedFile("b.jpg", JPEG, content_type="image/jpeg"),
            original_filename="b.jpg",
            mime_type="image/jpeg",
            file_size=len(JPEG),
            visibility=AttachmentVisibility.CUSTOMER,
        )

    def test_a_manager_of_another_tenant_cannot_promote(self):
        for actor in (self.other_manager, self.other_company_admin):
            with self.subTest(actor=actor.email):
                self.authenticate(actor)
                resp = self.set_visibility(
                    self.attachment, AttachmentVisibility.CUSTOMER
                )

                self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
                self.attachment.refresh_from_db()
                self.assertEqual(
                    self.attachment.visibility, AttachmentVisibility.INTERNAL
                )

    def test_an_attachment_from_another_ticket_is_not_reachable(self):
        # The other tenant's attachment id, on OUR ticket's URL.
        self.authenticate(self.manager)
        resp = self.set_visibility(
            self.other_attachment, AttachmentVisibility.CUSTOMER
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_customer_never_reaches_another_customers_released_photo(self):
        self.authenticate(self.customer_user)

        listing = self.list_attachments(ticket=self.other_ticket)
        download = self.download(
            self.other_attachment, ticket=self.other_ticket
        )

        self.assertEqual(listing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(download.status_code, status.HTTP_404_NOT_FOUND)


class CompletionEvidenceIsUnaffectedTests(_VisibilityFixture):
    """The thing this sprint could most easily have broken in silence.

    Both completion gates count `is_hidden=False` rows and neither reads
    `visibility`. A worker's INTERNAL photo is still evidence.
    """

    def test_an_internal_photo_still_counts_as_ticket_level_evidence(self):
        self.make_attachment(visibility=AttachmentVisibility.INTERNAL)
        self.assertTrue(_ticket_has_visible_attachment(self.ticket))

    def test_a_hidden_photo_still_does_not_count(self):
        self.make_attachment(
            uploaded_by=self.manager,
            is_hidden=True,
            visibility=AttachmentVisibility.INTERNAL,
        )
        self.assertFalse(_ticket_has_visible_attachment(self.ticket))

    def test_a_slot_completes_on_an_internal_photo_with_no_note(self):
        self.authenticate(self.staff)
        up = self.upload(staff_assignment_id=self.slot.id)

        self.assertEqual(up.status_code, status.HTTP_201_CREATED, up.data)
        self.assertEqual(up.data["visibility"], AttachmentVisibility.INTERNAL)

        resp = self.client.patch(
            f"/api/tickets/{self.ticket.id}/staff-assignments/{self.slot.id}/",
            {"slot_status": StaffAssignmentSlotStatus.COMPLETED},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.slot.refresh_from_db()
        self.assertEqual(
            self.slot.slot_status, StaffAssignmentSlotStatus.COMPLETED
        )


class PhaseIsNotVisibilityTests(_VisibilityFixture):
    def test_phase_defaults_to_unspecified_and_staff_may_label(self):
        self.authenticate(self.staff)
        plain = self.upload()
        labelled = self.upload(phase=AttachmentPhase.BEFORE)

        self.assertEqual(plain.data["phase"], AttachmentPhase.UNSPECIFIED)
        self.assertEqual(labelled.data["phase"], AttachmentPhase.BEFORE)
        # Labelling publishes nothing — this is the reference system's bug.
        self.assertEqual(
            labelled.data["visibility"], AttachmentVisibility.INTERNAL
        )

    def test_both_combinations_exist(self):
        before_public = self.make_attachment(
            phase=AttachmentPhase.BEFORE,
            visibility=AttachmentVisibility.CUSTOMER,
        )
        after_internal = self.make_attachment(
            phase=AttachmentPhase.AFTER,
            visibility=AttachmentVisibility.INTERNAL,
        )

        self.authenticate(self.customer_user)
        self.assertEqual(
            self.response_ids(self.list_attachments()), {before_public.id}
        )
        self.assertEqual(
            self.download(after_internal).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_promoting_does_not_touch_the_phase_label(self):
        attachment = self.make_attachment(
            phase=AttachmentPhase.AFTER,
            visibility=AttachmentVisibility.INTERNAL,
        )
        self.authenticate(self.manager)
        resp = self.set_visibility(attachment, AttachmentVisibility.CUSTOMER)

        self.assertEqual(resp.data["phase"], AttachmentPhase.AFTER)


class PerWorkPolicyTests(_VisibilityFixture):
    def test_provider_admin_sets_the_flag_and_the_next_upload_is_visible(self):
        self.authenticate(self.company_admin)
        resp = self.set_policy(True)

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["staff_uploads_customer_visible"])

        self.authenticate(self.staff)
        self.assertEqual(
            self.upload().data["visibility"], AttachmentVisibility.CUSTOMER
        )

    def test_the_flag_does_not_retro_promote_what_is_already_stored(self):
        stored = self.make_attachment(visibility=AttachmentVisibility.INTERNAL)

        self.authenticate(self.company_admin)
        self.set_policy(True)

        stored.refresh_from_db()
        self.assertEqual(stored.visibility, AttachmentVisibility.INTERNAL)

    def test_building_manager_staff_and_customer_are_all_refused(self):
        for actor in (self.manager, self.staff, self.customer_user):
            with self.subTest(actor=actor.email):
                self.authenticate(actor)
                resp = self.set_policy(True)

                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(
                    resp.data["code"],
                    "attachment_visibility_policy_forbidden",
                )

    def test_a_terminal_ticket_is_refused(self):
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save(update_fields=["status"])

        self.authenticate(self.company_admin)
        resp = self.set_policy(True)

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            resp.data["code"],
            "attachment_visibility_policy_not_allowed_terminal",
        )

    def test_a_provider_admin_of_another_tenant_gets_a_404(self):
        self.authenticate(self.other_company_admin)
        resp = self.set_policy(True)

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.ticket.refresh_from_db()
        self.assertFalse(self.ticket.staff_uploads_customer_visible)

    def test_the_flip_is_audited(self):
        self.authenticate(self.company_admin)
        self.set_policy(True)

        row = AuditLog.objects.filter(
            target_model="tickets.Ticket",
            target_id=self.ticket.id,
            action=AuditAction.UPDATE,
        ).latest("id")

        self.assertEqual(row.actor_id, self.company_admin.id)
        self.assertEqual(
            row.changes["staff_uploads_customer_visible"],
            {"before": False, "after": True},
        )
