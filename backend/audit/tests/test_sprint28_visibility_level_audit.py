"""
Sprint 28 Batch 10 — audit coverage for the new
`BuildingStaffVisibility.visibility_level` field.

Mirrors the Sprint 27B `can_request_assignment` audit shape: when an
admin PATCHes the per-row level via the BSV update endpoint, the
existing UPDATE-only handler writes exactly one `AuditLog` row carrying
the before/after diff. The `_BSV_TRACKED_FIELDS` tuple in
`audit/signals.py` is the single point of registration — Sprint 28
Batch 10 extends it to include `visibility_level`, no new handler
is added.

Boundaries:
  * The CREATE shape on `BuildingStaffVisibility` is unchanged — it
    still goes through `_on_membership_post_save` and emits the
    membership-style payload (user + building names).
  * UPDATE rows that don't touch `visibility_level` (e.g. only flipping
    `can_request_assignment`) continue to land per the Sprint 27B
    contract — the tracked tuple iterates both fields and only emits
    a diff entry per actually-changed field.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company, CompanyUserMembership


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


class VisibilityLevelAuditTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
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
            visibility_level=BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )

    def _detail_url(self):
        return (
            f"/api/users/{self.staff.id}/staff-visibility/"
            f"{self.building.id}/"
        )

    def test_update_emits_audit_row(self):
        before = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._detail_url(),
            {
                "visibility_level": (
                    BuildingStaffVisibility
                    .VisibilityLevel
                    .BUILDING_READ_AND_ASSIGN
                ),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.data["visibility_level"],
            BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )

        after_qs = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        )
        # Exactly one new UPDATE row for this PATCH.
        self.assertEqual(
            after_qs.count() - before,
            1,
            "Sprint 28 Batch 10 — a `visibility_level` PATCH must emit "
            "exactly one AuditLog UPDATE row.",
        )
        row = after_qs.latest("created_at")
        self.assertIn(
            "visibility_level",
            row.changes,
            "AuditLog row must carry `visibility_level` in `changes`.",
        )
        change = row.changes["visibility_level"]
        self.assertEqual(
            change.get("before"),
            BuildingStaffVisibility.VisibilityLevel.BUILDING_READ,
        )
        self.assertEqual(
            change.get("after"),
            BuildingStaffVisibility.VisibilityLevel.BUILDING_READ_AND_ASSIGN,
        )
