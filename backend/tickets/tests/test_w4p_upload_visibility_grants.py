"""
W4-P — the two permission scopes for staff photo uploads, and the
resolution order that decides between them.

Wave 3 (`test_sprint191_attachment_visibility.py`) pinned the customer
wall, the promote action and the per-work setting. This module extends
exactly that surface with the two things the owner asked for:

  GLOBAL / STANDING — this person's uploads are customer-visible on
                      EVERY ticket. Granted on the permissions screen.
  PER-TICKET        — this person's uploads are customer-visible on THIS
                      ticket only. Granted on the Assignment card.

WHAT THIS MODULE PINS

  1. THE RESOLUTION ORDER, EVERY COMBINATION. per-ticket > standing >
     per-work setting > default, most specific wins, internal by
     default. `ResolutionOrderTests` walks the full 3 x 3 x 2 grid — a
     per-ticket decision of grant/refuse/absent, crossed with the same
     three standing states, crossed with the per-work setting on and
     off. Eighteen rows, spelled out one by one rather than computed,
     because the point of the table is that a reader can check it
     against the rule by eye.
  2. THE SAME ANSWER THROUGH THE API. The grid is asserted against the
     resolver; `LadderThroughTheApiTests` then re-asserts the four
     interesting corners through a real multipart upload, so the rule
     that is tested is the rule that runs.
  3. GRANTING IS PRIVILEGED, AND NEVER SELF-SERVICE. Standing is
     SUPER_ADMIN / COMPANY_ADMIN only; per-ticket is provider
     management; nobody may decide their own uploads at either scope;
     STAFF and customer-side are refused everywhere.
  4. TENANT SCOPING (the P0). A COMPANY_ADMIN cannot reach a person
     outside their own company; a manager of another tenant cannot set a
     per-ticket grant; and — the one that matters most — a standing
     grant does NOT widen any queryset: the other tenant's customer
     still sees nothing, and our own customer still sees only their own
     ticket's photos.
  5. THE COMPLETION GATE IS STILL UNTOUCHED. A grant that refuses
     (`False`) keeps a worker's photo internal, and it still counts as
     completion evidence, because the gates read `is_hidden` and never
     `visibility`. This is wave 3's invariant (a), re-asserted against
     the new mechanism rather than assumed to survive it.
  6. AUDIT (H-10). A grant, a change, a refusal and a clear each write
     one AuditLog row naming the scope; a no-op write writes none.
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
from tickets.attachment_visibility import resolve_upload_visibility
from tickets.models import (
    AttachmentVisibility,
    TicketAttachment,
    TicketStaffAssignment,
    UploadVisibilityGrant,
    UploadVisibilitySource,
)
from tickets.state_machine import _ticket_has_visible_attachment


JPEG = b"\xff\xd8\xff\xe0"

INTERNAL = AttachmentVisibility.INTERNAL
CUSTOMER = AttachmentVisibility.CUSTOMER


@override_settings(MEDIA_ROOT="/tmp/cleaning-ticket-test-media")
class _GrantFixture(TenantFixtureMixin, APITestCase):
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

        # A second worker on the same ticket, so "this person" can be
        # shown to mean this person and not "anyone on this job".
        self.other_staff = self.make_user(
            "staff-a2@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=self.other_staff)
        BuildingStaffVisibility.objects.create(
            user=self.other_staff, building=self.building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.other_staff,
            assigned_by=self.manager,
        )

        # A worker on the OTHER tenant's ticket, for the P0 tests.
        self.foreign_staff = self.make_user(
            "staff-b@example.com", UserRole.STAFF
        )
        StaffProfile.objects.create(user=self.foreign_staff)
        BuildingStaffVisibility.objects.create(
            user=self.foreign_staff, building=self.other_building
        )
        TicketStaffAssignment.objects.create(
            ticket=self.other_ticket,
            user=self.foreign_staff,
            assigned_by=self.other_manager,
        )

    # ---- state setters ---------------------------------------------------
    def set_grant(self, user, value, *, ticket=None):
        """Write one rung directly. `None` means "no row at this rung"."""
        UploadVisibilityGrant.objects.filter(
            user=user, ticket=ticket
        ).delete()
        if value is not None:
            UploadVisibilityGrant.objects.create(
                user=user,
                ticket=ticket,
                uploads_customer_visible=value,
                granted_by=self.company_admin,
            )

    def set_work_setting(self, value, ticket=None):
        ticket = ticket or self.ticket
        ticket.staff_uploads_customer_visible = value
        ticket.save(update_fields=["staff_uploads_customer_visible"])

    # ---- HTTP helpers ----------------------------------------------------
    def upload(self, *, ticket=None, name="proof.jpg", **extra):
        ticket = ticket or self.ticket
        return self.client.post(
            f"/api/tickets/{ticket.id}/attachments/",
            {
                "file": SimpleUploadedFile(
                    name, JPEG, content_type="image/jpeg"
                ),
                **extra,
            },
            format="multipart",
        )

    def patch_standing(self, user, body):
        return self.client.patch(
            f"/api/tickets/upload-visibility/standing/{user.id}/",
            body,
            format="json",
        )

    def get_standing(self, user=None):
        suffix = f"?user_id={user.id}" if user is not None else ""
        return self.client.get(
            f"/api/tickets/upload-visibility/standing/{suffix}"
        )

    def patch_per_ticket(self, user, body, ticket=None):
        ticket = ticket or self.ticket
        return self.client.patch(
            f"/api/tickets/{ticket.id}/upload-visibility/{user.id}/",
            body,
            format="json",
        )

    def get_per_ticket(self, ticket=None):
        ticket = ticket or self.ticket
        return self.client.get(
            f"/api/tickets/{ticket.id}/upload-visibility/"
        )


class ResolutionOrderTests(_GrantFixture):
    """THE TABLE. per-ticket > standing > per-work > default.

    Every combination, written out. `None` in a rung column means "no
    decision at that rung"; True is a grant, False a refusal. The
    per-work column is a plain boolean because that rung has no
    "refuse" — its default False means "nobody opened this work up",
    which is an absence and falls through (see the resolver docstring).
    """

    # (per_ticket, standing, per_work) -> (visibility, source)
    GRID = [
        # --- rung 1 decides, in both directions, whatever is below it ---
        ((True, None, False), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        ((True, None, True), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        ((True, True, False), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        ((True, True, True), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        ((True, False, False), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        ((True, False, True), (CUSTOMER, UploadVisibilitySource.TICKET_GRANT)),
        # A per-ticket "no" beats a standing "yes" — the owner's own
        # worked example.
        ((False, None, False), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        ((False, None, True), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        ((False, True, False), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        ((False, True, True), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        ((False, False, False), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        ((False, False, True), (INTERNAL, UploadVisibilitySource.TICKET_GRANT)),
        # --- rung 1 silent: rung 2 decides ---
        # A standing "yes" beats the ABSENCE of a per-work setting.
        ((None, True, False), (CUSTOMER, UploadVisibilitySource.STANDING_GRANT)),
        ((None, True, True), (CUSTOMER, UploadVisibilitySource.STANDING_GRANT)),
        # A standing "no" beats a per-work "yes" — most specific wins.
        ((None, False, False), (INTERNAL, UploadVisibilitySource.STANDING_GRANT)),
        ((None, False, True), (INTERNAL, UploadVisibilitySource.STANDING_GRANT)),
        # --- rungs 1 and 2 silent: the per-work setting decides ---
        ((None, None, True), (CUSTOMER, UploadVisibilitySource.WORK_SETTING)),
        # --- nothing granted anywhere: internal, the default ---
        ((None, None, False), (INTERNAL, UploadVisibilitySource.DEFAULT_INTERNAL)),
    ]

    def test_every_combination(self):
        for (per_ticket, standing, per_work), expected in self.GRID:
            with self.subTest(
                per_ticket=per_ticket, standing=standing, per_work=per_work
            ):
                self.set_grant(self.staff, per_ticket, ticket=self.ticket)
                self.set_grant(self.staff, standing, ticket=None)
                self.set_work_setting(per_work)
                self.ticket.refresh_from_db()

                resolved = resolve_upload_visibility(self.ticket, self.staff)

                self.assertEqual(
                    (resolved.visibility, resolved.source), expected
                )

    def test_the_grid_is_complete(self):
        """A guard on the table itself: 3 x 3 x 2 and no duplicates. If
        a rung ever grows a state, this fails and somebody has to come
        back and write the new rows out."""
        keys = [key for key, _ in self.GRID]
        self.assertEqual(len(keys), 18)
        self.assertEqual(len(set(keys)), 18)

    def test_a_grant_is_about_one_person_not_the_job(self):
        self.set_grant(self.staff, True, ticket=None)

        self.assertTrue(
            resolve_upload_visibility(
                self.ticket, self.staff
            ).is_customer_visible
        )
        self.assertFalse(
            resolve_upload_visibility(
                self.ticket, self.other_staff
            ).is_customer_visible
        )

    def test_a_per_ticket_grant_does_not_leak_to_another_ticket(self):
        self.set_grant(self.staff, True, ticket=self.ticket)

        self.assertTrue(
            resolve_upload_visibility(
                self.ticket, self.staff
            ).is_customer_visible
        )
        self.assertFalse(
            resolve_upload_visibility(
                self.other_ticket, self.staff
            ).is_customer_visible
        )

    def test_a_customer_upload_sits_above_the_ladder(self):
        """Even a standing refusal cannot hide a customer's own file from
        them: that rule is above rung 1, not inside it."""
        self.set_grant(self.customer_user, False, ticket=None)

        resolved = resolve_upload_visibility(self.ticket, self.customer_user)

        self.assertEqual(resolved.visibility, CUSTOMER)
        self.assertEqual(
            resolved.source, UploadVisibilitySource.CUSTOMER_UPLOAD
        )


class LadderThroughTheApiTests(_GrantFixture):
    """The four corners of the grid, through a real upload, so the rule
    that is asserted is the rule the endpoint runs."""

    def test_standing_grant_puts_the_next_photo_in_the_pool(self):
        self.set_grant(self.staff, True, ticket=None)
        self.authenticate(self.staff)

        resp = self.upload()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["visibility"], CUSTOMER)
        self.assertEqual(
            resp.data["visibility_source"],
            UploadVisibilitySource.STANDING_GRANT,
        )

        # And the customer can actually see it — the point of the grant.
        self.authenticate(self.customer_user)
        listing = self.client.get(
            f"/api/tickets/{self.ticket.id}/attachments/"
        )
        self.assertIn(resp.data["id"], self.response_ids(listing))

    def test_a_per_ticket_refusal_overrides_a_standing_grant(self):
        self.set_grant(self.staff, True, ticket=None)
        self.set_grant(self.staff, False, ticket=self.ticket)
        self.authenticate(self.staff)

        resp = self.upload()

        self.assertEqual(resp.data["visibility"], INTERNAL)
        self.assertEqual(
            resp.data["visibility_source"],
            UploadVisibilitySource.TICKET_GRANT,
        )

        self.authenticate(self.customer_user)
        listing = self.client.get(
            f"/api/tickets/{self.ticket.id}/attachments/"
        )
        self.assertNotIn(resp.data["id"], self.response_ids(listing))

    def test_a_standing_refusal_overrides_the_per_work_setting(self):
        self.set_work_setting(True)
        self.set_grant(self.staff, False, ticket=None)
        self.authenticate(self.staff)

        resp = self.upload()

        self.assertEqual(resp.data["visibility"], INTERNAL)
        self.assertEqual(
            resp.data["visibility_source"],
            UploadVisibilitySource.STANDING_GRANT,
        )

    def test_with_nothing_granted_the_photo_is_still_internal(self):
        self.authenticate(self.staff)

        resp = self.upload()

        self.assertEqual(resp.data["visibility"], INTERNAL)
        self.assertEqual(
            resp.data["visibility_source"],
            UploadVisibilitySource.DEFAULT_INTERNAL,
        )

    def test_a_grant_never_rewrites_a_photo_that_is_already_stored(self):
        self.authenticate(self.staff)
        stored = self.upload()
        self.assertEqual(stored.data["visibility"], INTERNAL)

        self.set_grant(self.staff, True, ticket=None)

        row = TicketAttachment.objects.get(id=stored.data["id"])
        self.assertEqual(row.visibility, INTERNAL)
        self.assertEqual(
            row.visibility_source, UploadVisibilitySource.DEFAULT_INTERNAL
        )

    def test_a_hand_promote_says_it_was_a_hand_promote(self):
        self.authenticate(self.staff)
        stored = self.upload()

        self.authenticate(self.manager)
        resp = self.client.patch(
            f"/api/tickets/{self.ticket.id}/attachments/"
            f"{stored.data['id']}/visibility/",
            {"visibility": CUSTOMER},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            resp.data["visibility_source"], UploadVisibilitySource.MANUAL
        )

    def test_provider_management_typing_a_value_still_wins(self):
        self.set_grant(self.manager, False, ticket=None)
        self.authenticate(self.manager)

        resp = self.upload(visibility=CUSTOMER)

        self.assertEqual(resp.data["visibility"], CUSTOMER)
        self.assertEqual(
            resp.data["visibility_source"],
            UploadVisibilitySource.UPLOADER_CHOICE,
        )


class StandingGrantEndpointTests(_GrantFixture):
    """The permissions screen's write surface: every ticket, forever."""

    def test_company_admin_grants_and_the_read_reflects_it(self):
        self.authenticate(self.company_admin)
        resp = self.patch_standing(
            self.staff,
            {"uploads_customer_visible": True, "reason": "trusted"},
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["uploads_customer_visible"])
        self.assertEqual(resp.data["reason"], "trusted")
        self.assertEqual(resp.data["ticket_id"], None)
        self.assertEqual(resp.data["granted_by_id"], self.company_admin.id)

        read = self.get_standing(self.staff)
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertTrue(read.data["uploads_customer_visible"])

    def test_super_admin_may_grant_too(self):
        self.authenticate(self.super_admin)
        resp = self.patch_standing(
            self.staff, {"uploads_customer_visible": True}
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_null_clears_and_is_not_the_same_as_false(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": False})
        self.assertEqual(
            UploadVisibilityGrant.objects.filter(
                user=self.staff, ticket__isnull=True
            ).count(),
            1,
        )

        resp = self.patch_standing(
            self.staff, {"uploads_customer_visible": None}
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertIsNone(resp.data["uploads_customer_visible"])
        self.assertFalse(
            UploadVisibilityGrant.objects.filter(
                user=self.staff, ticket__isnull=True
            ).exists()
        )

    def test_the_key_is_required(self):
        self.authenticate(self.company_admin)
        resp = self.patch_standing(self.staff, {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_second_write_updates_the_one_row(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": True})
        self.patch_standing(self.staff, {"uploads_customer_visible": False})

        rows = UploadVisibilityGrant.objects.filter(
            user=self.staff, ticket__isnull=True
        )
        self.assertEqual(rows.count(), 1)
        self.assertFalse(rows.first().uploads_customer_visible)

    def test_the_list_read_shows_only_standing_rows(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": True})
        self.patch_per_ticket(
            self.other_staff, {"uploads_customer_visible": True}
        )

        resp = self.get_standing()

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row["user_id"] for row in resp.data], [self.staff.id]
        )


class GrantingIsPrivilegedTests(_GrantFixture):
    """Who may give this permission. Not the person receiving it."""

    def test_nobody_grants_themselves_standing(self):
        self.authenticate(self.company_admin)
        resp = self.patch_standing(
            self.company_admin, {"uploads_customer_visible": True}
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "upload_visibility_self_grant_forbidden")
        self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_not_even_a_super_admin_grants_themselves(self):
        self.authenticate(self.super_admin)
        resp = self.patch_standing(
            self.super_admin, {"uploads_customer_visible": True}
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "upload_visibility_self_grant_forbidden")

    def test_nobody_grants_themselves_per_ticket(self):
        """A manager who also holds a slot on the ticket still cannot
        decide their own uploads there."""
        TicketStaffAssignment.objects.create(
            ticket=self.ticket,
            user=self.manager,
            assigned_by=self.company_admin,
        )
        self.authenticate(self.manager)

        resp = self.patch_per_ticket(
            self.manager, {"uploads_customer_visible": True}
        )

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data["code"], "upload_visibility_self_grant_forbidden")

    def test_staff_cannot_grant_at_either_scope(self):
        self.authenticate(self.staff)

        standing = self.patch_standing(
            self.other_staff, {"uploads_customer_visible": True}
        )
        per_ticket = self.patch_per_ticket(
            self.other_staff, {"uploads_customer_visible": True}
        )

        self.assertEqual(standing.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(standing.data["code"], "upload_visibility_forbidden")
        self.assertEqual(per_ticket.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            per_ticket.data["code"], "upload_visibility_forbidden"
        )
        self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_a_customer_cannot_grant_at_either_scope(self):
        self.authenticate(self.customer_user)

        standing = self.patch_standing(
            self.staff, {"uploads_customer_visible": True}
        )
        per_ticket = self.patch_per_ticket(
            self.staff, {"uploads_customer_visible": True}
        )

        self.assertEqual(standing.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(per_ticket.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_a_building_manager_may_do_per_ticket_but_not_standing(self):
        """The line this sprint draws, and the reason for it: a
        per-ticket grant is a pre-authorised promote, which a BM can
        already do photo by photo. A standing grant spans every ticket
        of every customer and is a provider-admin act."""
        self.authenticate(self.manager)

        per_ticket = self.patch_per_ticket(
            self.staff, {"uploads_customer_visible": True}
        )
        standing = self.patch_standing(
            self.staff, {"uploads_customer_visible": True}
        )

        self.assertEqual(per_ticket.status_code, status.HTTP_200_OK)
        self.assertEqual(standing.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(standing.data["code"], "upload_visibility_forbidden")

    def test_the_role_gate_answers_before_the_object_lookup(self):
        """A wrong role learns nothing about which tickets or users
        exist (H-1): 403, not a scope-driven 404."""
        self.authenticate(self.staff)
        resp = self.client.patch(
            "/api/tickets/upload-visibility/standing/999999/",
            {"uploads_customer_visible": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TenantScopingTests(_GrantFixture):
    """The P0. A permission must never let a photo cross a company or
    customer boundary."""

    def test_a_company_admin_cannot_reach_a_person_of_another_tenant(self):
        self.authenticate(self.company_admin)
        resp = self.patch_standing(
            self.foreign_staff, {"uploads_customer_visible": True}
        )

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_a_manager_of_another_tenant_cannot_set_a_per_ticket_grant(self):
        for actor in (self.other_manager, self.other_company_admin):
            with self.subTest(actor=actor.email):
                self.authenticate(actor)
                resp = self.patch_per_ticket(
                    self.staff, {"uploads_customer_visible": True}
                )

                self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
                self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_a_per_ticket_grant_needs_the_person_to_work_here(self):
        self.authenticate(self.company_admin)
        resp = self.patch_per_ticket(
            self.foreign_staff, {"uploads_customer_visible": True}
        )

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(UploadVisibilityGrant.objects.exists())

    def test_a_standing_grant_does_not_widen_any_queryset(self):
        """The heart of the P0: the grant changes the LEVEL an upload
        lands at, never who may read a stored row. A photo released by a
        standing grant on OUR ticket stays invisible to the other
        tenant's customer, and the other tenant's ticket stays
        unreachable to ours."""
        self.set_grant(self.staff, True, ticket=None)
        self.authenticate(self.staff)
        ours = self.upload()
        self.assertEqual(ours.data["visibility"], CUSTOMER)

        # The other tenant's customer: 404 on the ticket, nothing to see.
        self.authenticate(self.other_customer_user)
        self.assertEqual(
            self.client.get(
                f"/api/tickets/{self.ticket.id}/attachments/"
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(
                f"/api/tickets/{self.ticket.id}/attachments/"
                f"{ours.data['id']}/download/"
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

        # Our own customer sees their own ticket's photo and nothing of
        # the other tenant's.
        self.authenticate(self.customer_user)
        self.assertIn(
            ours.data["id"],
            self.response_ids(
                self.client.get(
                    f"/api/tickets/{self.ticket.id}/attachments/"
                )
            ),
        )
        self.assertEqual(
            self.client.get(
                f"/api/tickets/{self.other_ticket.id}/attachments/"
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_a_grant_on_the_other_tenants_worker_stays_over_there(self):
        """Written straight to the DB so the endpoint's own gate is not
        what is being tested: even with the row present, the resolver
        answers per ticket, and our customer is unaffected."""
        self.set_grant(self.foreign_staff, True, ticket=None)

        self.assertTrue(
            resolve_upload_visibility(
                self.other_ticket, self.foreign_staff
            ).is_customer_visible
        )
        self.assertFalse(
            resolve_upload_visibility(
                self.ticket, self.staff
            ).is_customer_visible
        )

    def test_the_per_ticket_read_is_scoped(self):
        self.authenticate(self.other_manager)
        self.assertEqual(
            self.get_per_ticket().status_code, status.HTTP_404_NOT_FOUND
        )


class PerTicketEndpointTests(_GrantFixture):
    """The Assignment card's surface — the contract chat M builds on."""

    def test_the_read_lists_one_entry_per_person_with_every_rung(self):
        self.set_grant(self.staff, True, ticket=self.ticket)
        self.set_grant(self.other_staff, True, ticket=None)
        self.authenticate(self.manager)

        resp = self.get_per_ticket()

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["ticket_id"], self.ticket.id)
        self.assertFalse(resp.data["staff_uploads_customer_visible"])

        by_id = {row["user_id"]: row for row in resp.data["people"]}
        self.assertEqual(set(by_id), {self.staff.id, self.other_staff.id})

        granted = by_id[self.staff.id]
        self.assertTrue(granted["uploads_customer_visible"])
        self.assertIsNone(granted["standing_uploads_customer_visible"])
        self.assertEqual(granted["effective_visibility"], CUSTOMER)
        self.assertEqual(
            granted["effective_source"], UploadVisibilitySource.TICKET_GRANT
        )

        standing_only = by_id[self.other_staff.id]
        self.assertIsNone(standing_only["uploads_customer_visible"])
        self.assertTrue(standing_only["standing_uploads_customer_visible"])
        self.assertEqual(standing_only["effective_visibility"], CUSTOMER)
        self.assertEqual(
            standing_only["effective_source"],
            UploadVisibilitySource.STANDING_GRANT,
        )

    def test_a_person_with_two_slots_appears_once(self):
        TicketStaffAssignment.objects.create(
            ticket=self.ticket, user=self.staff, assigned_by=self.manager
        )
        self.authenticate(self.manager)

        resp = self.get_per_ticket()

        ids = [row["user_id"] for row in resp.data["people"]]
        self.assertEqual(ids.count(self.staff.id), 1)

    def test_the_write_answers_with_the_new_effective_state(self):
        self.authenticate(self.manager)
        resp = self.patch_per_ticket(
            self.staff, {"uploads_customer_visible": False}
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertFalse(resp.data["uploads_customer_visible"])
        self.assertEqual(resp.data["effective_visibility"], INTERNAL)
        self.assertEqual(
            resp.data["effective_source"],
            UploadVisibilitySource.TICKET_GRANT,
        )

    def test_clearing_falls_back_to_the_rung_below(self):
        self.set_grant(self.staff, True, ticket=None)
        self.authenticate(self.manager)
        self.patch_per_ticket(self.staff, {"uploads_customer_visible": False})

        resp = self.patch_per_ticket(
            self.staff, {"uploads_customer_visible": None}
        )

        self.assertIsNone(resp.data["uploads_customer_visible"])
        self.assertEqual(resp.data["effective_visibility"], CUSTOMER)
        self.assertEqual(
            resp.data["effective_source"],
            UploadVisibilitySource.STANDING_GRANT,
        )


class CompletionEvidenceSurvivesAGrantTests(_GrantFixture):
    """Wave 3's invariant (a), re-asserted against the new mechanism.

    The gates count `is_hidden=False` rows and never read `visibility`,
    so a refusal keeps a worker's photo internal WITHOUT taking away the
    proof that the work happened."""

    def test_a_refused_photo_is_still_ticket_level_evidence(self):
        self.set_grant(self.staff, False, ticket=None)
        self.authenticate(self.staff)
        resp = self.upload()

        self.assertEqual(resp.data["visibility"], INTERNAL)
        self.ticket.refresh_from_db()
        self.assertTrue(_ticket_has_visible_attachment(self.ticket))

    def test_a_granted_photo_is_evidence_too(self):
        self.set_grant(self.staff, True, ticket=None)
        self.authenticate(self.staff)
        resp = self.upload()

        self.assertEqual(resp.data["visibility"], CUSTOMER)
        self.ticket.refresh_from_db()
        self.assertTrue(_ticket_has_visible_attachment(self.ticket))

    def test_a_slot_still_completes_on_a_refused_photo_with_no_note(self):
        self.set_grant(self.staff, False, ticket=self.ticket)
        self.authenticate(self.staff)
        up = self.upload(staff_assignment_id=self.slot.id)
        self.assertEqual(up.data["visibility"], INTERNAL)

        resp = self.client.patch(
            f"/api/tickets/{self.ticket.id}/staff-assignments/{self.slot.id}/",
            {"slot_status": "COMPLETED"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)


class GrantAuditTests(_GrantFixture):
    """H-10 — every permission change writes an AuditLog row."""

    def rows(self):
        return AuditLog.objects.filter(
            target_model="tickets.UploadVisibilityGrant",
            action=AuditAction.UPDATE,
        ).order_by("id")

    def test_a_standing_grant_is_audited_with_its_scope(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": True})

        row = self.rows().latest("id")
        self.assertEqual(row.actor_id, self.company_admin.id)
        self.assertEqual(row.target_id, self.staff.id)
        self.assertEqual(row.changes["scope"], "STANDING")
        self.assertIsNone(row.changes["ticket_id"])
        self.assertEqual(
            row.changes["uploads_customer_visible"],
            {"before": None, "after": True},
        )

    def test_a_per_ticket_grant_names_the_ticket(self):
        self.authenticate(self.manager)
        self.patch_per_ticket(self.staff, {"uploads_customer_visible": True})

        row = self.rows().latest("id")
        self.assertEqual(row.changes["scope"], "TICKET")
        self.assertEqual(row.changes["ticket_id"], self.ticket.id)

    def test_a_refusal_and_a_clear_are_each_audited(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": True})
        self.patch_standing(self.staff, {"uploads_customer_visible": False})
        self.patch_standing(self.staff, {"uploads_customer_visible": None})

        changes = [
            row.changes["uploads_customer_visible"] for row in self.rows()
        ]
        self.assertEqual(
            changes,
            [
                {"before": None, "after": True},
                {"before": True, "after": False},
                {"before": False, "after": None},
            ],
        )

    def test_a_no_op_write_writes_no_row(self):
        self.authenticate(self.company_admin)
        self.patch_standing(self.staff, {"uploads_customer_visible": True})
        before = self.rows().count()

        self.patch_standing(self.staff, {"uploads_customer_visible": True})

        self.assertEqual(self.rows().count(), before)
