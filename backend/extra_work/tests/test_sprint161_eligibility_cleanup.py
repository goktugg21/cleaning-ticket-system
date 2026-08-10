"""
Sprint 161 §6 — the data migration that removes pre-eligibility
assignment rows.

The migration function is called DIRECTLY with the real app registry.
`apps.get_model("extra_work", "ExtraWorkAssignment")` resolves the same
way against the real registry as against a migration state, and the
function contains no schema-state dependency, so this exercises the
actual code that will run rather than a paraphrase of it.

Why a test at all, when the migration is a no-op on the dev database:
the rows it targets live on crmtest (the brief names requests 68 and 69,
where two STAFF users are stored as MANAGER), and this session neither
deploys nor touches that database. So the only honest way to show the
migration does what it claims is to build the condition and watch it.
"""
import importlib
from django.apps import apps as real_apps
from rest_framework.test import APITestCase

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkStatus,
)
from test_utils import TenantFixtureMixin

# A migration module name starts with a digit, so it is not a valid
# identifier and cannot be reached with `import ... from`. importlib is
# the only way, and using the REAL module matters: a copy of the
# function here would be the paraphrase this test exists to avoid.
drop_ineligible_assignments = importlib.import_module(
    "extra_work.migrations.0029_sprint161_drop_ineligible_assignments"
).drop_ineligible_assignments


class EligibilityCleanupTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.request = ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.super_admin,
            title="Pre-eligibility",
            description="x",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=ExtraWorkStatus.REQUESTED,
        )

    def _assign(self, user, role):
        return ExtraWorkAssignment.objects.create(
            extra_work_request=self.request, user=user, role=role
        )

    def run_migration(self):
        with self.assertLogs("extra_work.migrations", level="WARNING") as logs:
            drop_ineligible_assignments(real_apps, None)
        return logs.output

    def test_a_staff_user_stored_as_manager_is_removed(self):
        """The exact crmtest shape: STAFF holding MANAGER."""
        staff = self.make_user("s161-staff@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=staff, building=self.building
        )
        row = self._assign(staff, ExtraWorkAssignmentRole.MANAGER)

        output = self.run_migration()

        self.assertFalse(
            ExtraWorkAssignment.objects.filter(pk=row.pk).exists()
        )
        self.assertTrue(
            any("removing ineligible" in line for line in output),
            f"the removal was not logged: {output}",
        )
        self.assertTrue(
            any(str(staff.id) in line for line in output),
            "the log does not say WHICH user was removed",
        )

    def test_a_legitimate_manager_is_left_alone(self):
        """Do not delete anything that is still legitimate."""
        manager = self.make_user(
            "s161-real-manager@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=manager, building=self.building
        )
        row = self._assign(manager, ExtraWorkAssignmentRole.MANAGER)

        self.run_migration()

        self.assertTrue(ExtraWorkAssignment.objects.filter(pk=row.pk).exists())

    def test_a_legitimate_worker_is_left_alone(self):
        worker = self.make_user("s161-real-worker@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=worker, building=self.building
        )
        row = self._assign(worker, ExtraWorkAssignmentRole.WORKER)

        self.run_migration()

        self.assertTrue(ExtraWorkAssignment.objects.filter(pk=row.pk).exists())

    def test_it_removes_only_the_wrong_rows(self):
        """The two together, so the test cannot pass by deleting
        everything or by deleting nothing."""
        good = self.make_user("s161-good@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=good, building=self.building)
        bad = self.make_user("s161-bad@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=bad, building=self.building)

        good_row = self._assign(good, ExtraWorkAssignmentRole.WORKER)
        bad_row = self._assign(bad, ExtraWorkAssignmentRole.MANAGER)

        self.run_migration()

        self.assertTrue(
            ExtraWorkAssignment.objects.filter(pk=good_row.pk).exists()
        )
        self.assertFalse(
            ExtraWorkAssignment.objects.filter(pk=bad_row.pk).exists()
        )

    def test_it_reports_what_it_examined_and_removed(self):
        staff = self.make_user("s161-count@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=staff, building=self.building)
        self._assign(staff, ExtraWorkAssignmentRole.MANAGER)

        output = self.run_migration()

        self.assertTrue(
            any("examined 1 assignment rows, removed 1" in line for line in output),
            f"no summary line: {output}",
        )

    def test_running_it_twice_is_safe(self):
        staff = self.make_user("s161-twice@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(user=staff, building=self.building)
        self._assign(staff, ExtraWorkAssignmentRole.MANAGER)

        self.run_migration()
        # Second pass: nothing left to remove, and it must not raise.
        with self.assertLogs("extra_work.migrations", level="WARNING") as logs:
            drop_ineligible_assignments(real_apps, None)
        self.assertTrue(
            any("removed 0" in line for line in logs.output), logs.output
        )

    # A "request with no building" test was written and then removed:
    # `ExtraWorkRequest.building` is NOT NULL, so the case cannot be
    # constructed. The migration keeps the guard anyway (see its
    # comment); what it cannot have is a test, and inventing one that
    # bypassed the constraint would have been testing a fiction.
