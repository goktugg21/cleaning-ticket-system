"""
Sprint 27A — RBAC safety net (audit app).

T-7  test_building_staff_visibility_can_request_assignment_update_is_audited

Locks the audit shape for the per-building `can_request_assignment`
toggle on `BuildingStaffVisibility`: every UPDATE produces an
`AuditLog` row with the before/after pair on `changes`.

History:
  * Sprint 27A landed this test as `@unittest.expectedFailure` —
    on master @ 95748b3 the audit signal registration treated
    `BuildingStaffVisibility` as CREATE/DELETE-only and the
    UPDATE was silently dropped (gap G-B4 in
    docs/architecture/sprint-27-rbac-matrix.md).
  * Sprint 27B added a dedicated pre_save snapshot + post_save
    UPDATE-only handler for the model in `audit/signals.py`,
    keeping the existing membership CREATE/DELETE shape unchanged.
    The expectedFailure decorator was removed and the test now
    asserts the corrected behaviour directly.

See section H-10 + gap G-B4 (now marked closed by Sprint 27B) in
docs/architecture/sprint-27-rbac-matrix.md.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import StaffProfile, UserRole
from audit.models import AuditAction, AuditLog
from buildings.models import Building, BuildingStaffVisibility
from companies.models import Company


User = get_user_model()
PASSWORD = "StrongerTestPassword123!"


class BuildingStaffVisibilityUpdateAuditTests(TestCase):
    """T-7 — locks the future fix for G-B4."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Co A", slug="co-a")
        cls.building = Building.objects.create(
            company=cls.company, name="B1"
        )
        cls.staff = User.objects.create_user(
            email="staff@example.com",
            password=PASSWORD,
            role=UserRole.STAFF,
            full_name="Staff",
        )
        StaffProfile.objects.create(user=cls.staff)
        cls.visibility = BuildingStaffVisibility.objects.create(
            user=cls.staff,
            building=cls.building,
            can_request_assignment=True,
        )

    def test_building_staff_visibility_can_request_assignment_update_is_audited(
        self,
    ):
        """T-7: toggling `can_request_assignment` writes an
        AuditLog UPDATE row carrying the before/after pair.

        Closed in Sprint 27B by a dedicated pre_save/post_save
        UPDATE-only handler in `audit/signals.py` (the CREATE/DELETE
        shape on `BuildingStaffVisibility` is unchanged — those
        still go through the existing membership handlers).
        """
        # Snapshot: no UPDATE row for this visibility row yet.
        before = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        ).count()

        # Toggle the per-building override.
        self.visibility.can_request_assignment = False
        self.visibility.save(update_fields=["can_request_assignment"])

        after = AuditLog.objects.filter(
            target_model="buildings.BuildingStaffVisibility",
            target_id=self.visibility.id,
            action=AuditAction.UPDATE,
        )
        self.assertEqual(
            after.count() - before,
            1,
            "BuildingStaffVisibility.can_request_assignment UPDATE "
            "must be audited — Sprint 27A documented gap G-B4, "
            "scheduled for Sprint 27B.",
        )
        row = after.latest("created_at")
        self.assertIn(
            "can_request_assignment",
            row.changes,
            "AuditLog row must carry the changed field in `changes`.",
        )
        change = row.changes["can_request_assignment"]
        self.assertEqual(change.get("before"), True)
        self.assertEqual(change.get("after"), False)
