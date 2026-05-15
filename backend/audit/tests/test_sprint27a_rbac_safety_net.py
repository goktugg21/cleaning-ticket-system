"""
Sprint 27A — RBAC safety net (audit app).

T-7  test_building_staff_visibility_can_request_assignment_update_is_audited

DOCUMENTED GAP (G-B4): on master @ 95748b3 the audit signal
registration at [audit/signals.py:454-471] treats
`BuildingStaffVisibility` as a CREATE/DELETE-only membership.
Toggling `can_request_assignment` on an existing visibility row
therefore leaves no `AuditLog` row, while every other
"permission toggle" surface (`StaffProfile.is_active`,
`Customer.show_assigned_staff_*`, `CustomerUserBuildingAccess.
permission_overrides`) IS audited.

This test asserts the corrected future behaviour: every UPDATE
to `BuildingStaffVisibility.can_request_assignment` produces an
`AuditLog` row with the before/after pair. It is decorated with
`@unittest.expectedFailure` so the CI / full test suite stays
green while still keeping the assertion alive as a regression
lock — the moment Sprint 27B lands the audit signal fix, this
test will start passing and the `expectedFailure` decorator must
be removed (an unexpected success is a test-level failure under
unittest, so CI will surface the green flip automatically).

See section H-10 + gap G-B4 in
docs/architecture/sprint-27-rbac-matrix.md.

Sprint 27B TODO: when the BuildingStaffVisibility audit signal
fix lands (promoting it from membership-only signal group into
the fully-tracked group, or adding a custom field-diff handler
for `can_request_assignment`), DELETE the `@unittest.expectedFailure`
decorator on the test below. The test body itself does not need
to change.
"""
from __future__ import annotations

import unittest

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

    # Sprint 27A documents gap G-B4:
    #   * BuildingStaffVisibility.can_request_assignment UPDATEs are
    #     NOT audited on master @ 95748b3 (only CREATE/DELETE on the
    #     visibility row itself are tracked).
    #   * The assertion below describes the corrected future shape.
    #   * Sprint 27B should remove this @unittest.expectedFailure
    #     decorator once the audit signal fix lands; an unexpected
    #     success will surface in CI automatically so we cannot
    #     accidentally ship the fix without unflipping this test.
    @unittest.expectedFailure
    def test_building_staff_visibility_can_request_assignment_update_is_audited(
        self,
    ):
        """T-7: toggling can_request_assignment must write an
        AuditLog UPDATE row carrying the before/after pair.

        Wrapped in @unittest.expectedFailure today — documented as
        gap G-B4. Sprint 27B will promote BuildingStaffVisibility
        from the membership-only signal group into the fully-tracked
        group (or register a custom field-diff handler for the
        can_request_assignment field) and at the same time remove
        this decorator.
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
