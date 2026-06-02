"""
Sprint 13C — audit coverage for the new
`StaffProfile.employment_type` field.

StaffProfile is in the full-CRUD audit trio (audit/signals.py): the
generic `_on_pre_save` / `_on_post_save` handlers snapshot and diff
ALL concrete fields via `audit.diff._snapshot`, which auto-introspects
`instance._meta.get_fields()`. So no `signals.py` registration step is
needed for a new concrete field — it is picked up automatically. This
file pins that contract: a PATCH that changes `employment_type` writes
exactly one AuditLog UPDATE row for `accounts.StaffProfile` carrying the
before/after employment_type diff.
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


class EmploymentTypeAuditTests(APITestCase):
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
        cls.profile = StaffProfile.objects.create(
            user=cls.staff,
            employment_type=StaffProfile.EmploymentType.INTERNAL_STAFF,
        )
        # Visibility so the SA endpoint resolves the staff in scope (and
        # mirrors the production shape; SA passes regardless).
        BuildingStaffVisibility.objects.create(
            user=cls.staff, building=cls.building
        )

    def _profile_url(self):
        return f"/api/users/{self.staff.id}/staff-profile/"

    def _update_rows(self, *, since: int):
        qs = AuditLog.objects.filter(
            target_model="accounts.StaffProfile",
            target_id=self.profile.id,
            action=AuditAction.UPDATE,
        ).order_by("created_at")
        return list(qs[since:])

    def test_patch_employment_type_emits_single_update_row_with_diff(self):
        before_count = AuditLog.objects.filter(
            target_model="accounts.StaffProfile",
            target_id=self.profile.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._profile_url(),
            {"employment_type": StaffProfile.EmploymentType.ZZP},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.data["employment_type"],
            StaffProfile.EmploymentType.ZZP,
        )

        new_rows = self._update_rows(since=before_count)
        self.assertEqual(
            len(new_rows),
            1,
            "Sprint 13C — changing employment_type must emit exactly one "
            "AuditLog UPDATE row for StaffProfile.",
        )
        row = new_rows[0]
        self.assertEqual(row.actor_id, self.super_admin.id)
        self.assertIn("employment_type", row.changes)
        change = row.changes["employment_type"]
        self.assertEqual(change.get("before"), "INTERNAL_STAFF")
        self.assertEqual(change.get("after"), "ZZP")

    def test_no_op_patch_does_not_emit_employment_type_diff(self):
        # PATCHing the same value writes no UPDATE row (the diff engine
        # skips when nothing meaningful changed).
        self.profile.refresh_from_db()
        self.profile.employment_type = StaffProfile.EmploymentType.INHUUR
        self.profile.save(update_fields=["employment_type"])

        before_count = AuditLog.objects.filter(
            target_model="accounts.StaffProfile",
            target_id=self.profile.id,
            action=AuditAction.UPDATE,
        ).count()

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            self._profile_url(),
            {"employment_type": StaffProfile.EmploymentType.INHUUR},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        new_rows = self._update_rows(since=before_count)
        self.assertEqual(
            len(new_rows),
            0,
            "A no-op PATCH (same employment_type) must not emit an "
            "AuditLog UPDATE row.",
        )
