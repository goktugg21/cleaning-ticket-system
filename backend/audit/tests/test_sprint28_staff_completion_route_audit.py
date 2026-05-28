"""
Sprint 28 Batch 11 — audit coverage for the new
`BuildingStaffVisibility.staff_completion_routes_to_customer` flag.

Mirrors the Sprint 27B `can_request_assignment` and Sprint 28 Batch 10
`visibility_level` shapes: extending `_BSV_TRACKED_FIELDS` is the
single registration point. The existing UPDATE-only handler emits
exactly one `AuditLog` UPDATE row per PATCH, with `changes` keyed by
the field name and the before/after diff.

What this file locks:

  * PATCHing only `staff_completion_routes_to_customer` False -> True
    emits one row with that key in `changes`.
  * PATCHing `staff_completion_routes_to_customer` AND
    `visibility_level` in the same call emits ONE row carrying both
    diffs (no double-write).
  * PATCHing an unrelated tracked field (`can_request_assignment`)
    does not include the routing flag in `changes` (per-field
    iteration in the handler is honest about what actually changed).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


def _mk(email, role, **extra):
    return User.objects.create_user(
        email=email,
        password=PASSWORD,
        role=role,
        full_name=email.split("@")[0],
        **extra,
    )


class StaffCompletionRouteFlagAuditTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(company=cls.company, name="B1")
        cls.super_admin = _mk(
            "super@example.com",
            UserRole.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.staff = _mk("staff@example.com", UserRole.STAFF)
        StaffProfile.objects.create(user=cls.staff)
        cls.visibility = BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            staff_completion_routes_to_customer=False,
            can_request_assignment=True,
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )

    def _detail_url(self):
        return (
            f"/api/users/{self.staff.id}/staff-visibility/"
            f"{self.building.id}/"
        )

    def _latest_update_rows(self, *, since: int) -> list[AuditLog]:
        qs = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).order_by("created_at")
        return list(qs[since:])

    def test_patch_flag_false_to_true_emits_audit_row(self):
        before_count = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._detail_url(),
            {"staff_completion_routes_to_customer": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(response.data["staff_completion_routes_to_customer"])

        new_rows = self._latest_update_rows(since=before_count)
        self.assertEqual(
            len(new_rows),
            1,
            "Sprint 28 Batch 11 — flipping `staff_completion_routes_to_customer` "
            "must emit exactly one AuditLog UPDATE row.",
        )
        row = new_rows[0]
        self.assertIn("staff_completion_routes_to_customer", row.changes)
        change = row.changes["staff_completion_routes_to_customer"]
        self.assertEqual(change.get("before"), False)
        self.assertEqual(change.get("after"), True)

    def test_patch_flag_and_visibility_level_emits_single_row_with_both_diffs(self):
        before_count = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._detail_url(),
            {
                "staff_completion_routes_to_customer": True,
                "visibility_level": (
                    BuildingStaffVisibility
                    .VisibilityLevel
                    .BUILDING_READ_AND_ASSIGN
                ),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        new_rows = self._latest_update_rows(since=before_count)
        self.assertEqual(
            len(new_rows),
            1,
            "A single PATCH must produce a single AuditLog UPDATE row "
            "even when multiple tracked fields change.",
        )
        row = new_rows[0]
        self.assertIn("staff_completion_routes_to_customer", row.changes)
        self.assertIn("visibility_level", row.changes)

    def test_patch_unrelated_field_does_not_include_flag(self):
        # Reset baseline: ensure the visibility row's tracked fields
        # have a known state before this test PATCHes one.
        self.visibility.can_request_assignment = True
        self.visibility.save(update_fields=["can_request_assignment"])

        before_count = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._detail_url(),
            {"can_request_assignment": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        new_rows = self._latest_update_rows(since=before_count)
        self.assertEqual(
            len(new_rows),
            1,
            "Toggling an unrelated tracked field must still emit one row.",
        )
        row = new_rows[0]
        self.assertIn("can_request_assignment", row.changes)
        self.assertNotIn(
            "staff_completion_routes_to_customer",
            row.changes,
            "Toggling `can_request_assignment` alone must NOT include "
            "`staff_completion_routes_to_customer` in the diff payload.",
        )
