"""
Sprint 159 §2 — managers AND workers in ONE request.

The owner's complaint was about the UI, but the fix has to reach the
endpoint or the client is just firing two requests behind one button —
and two requests means a half-staffed job whenever the second one fails.

What is pinned here:

  1. **One body assigns both roles**, and the rows land in the right
     role each.
  2. **Still all-or-nothing across roles.** An ineligible MANAGER
     rejects the WORKERS in the same body, with zero writes. This is the
     property a client-side loop cannot have.
  3. **Still no oracle (H-1).** A foreign id and a fictional id produce
     EQUAL response bodies — compared for equality, because two 400s
     with different wording still answer "does this id exist".
  4. **Re-assignment is counted, not an error**, in the combined shape
     exactly as in the single-role one.
  5. **The Sprint 157 single-role body still works.** It is what the
     detail page's remove path speaks.
"""
from rest_framework import status

from accounts.models import UserRole
from buildings.models import BuildingManagerAssignment, BuildingStaffVisibility
from extra_work.models import ExtraWorkAssignment, ExtraWorkAssignmentRole

from .test_sprint157_assignments import BULK_URL, ExtraWorkAssignmentTestBase


class CombinedAssignTests(ExtraWorkAssignmentTestBase):
    def setUp(self):
        super().setUp()
        # A second worker and a second manager, both eligible at
        # `self.building`, so a body can name two of each.
        self.worker_two = self.make_user("ew159-w2@example.com", UserRole.STAFF)
        BuildingStaffVisibility.objects.create(
            user=self.worker_two, building=self.building
        )
        self.manager_two = self.make_user(
            "ew159-m2@example.com", UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.manager_two, building=self.building
        )

    def _combined(self, workers, managers, requests=None, mode="assign"):
        return {
            "requests": [r.id for r in (requests or [self.request_a])],
            "workers": [u.id for u in workers],
            "managers": [u.id for u in managers],
            "mode": mode,
        }

    def test_one_body_assigns_both_roles(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._combined([self.staff, self.worker_two], [self.manager]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 3)

        rows = ExtraWorkAssignment.objects.filter(
            extra_work_request=self.request_a
        )
        self.assertEqual(rows.count(), 3)
        self.assertEqual(
            set(
                rows.filter(role=ExtraWorkAssignmentRole.WORKER).values_list(
                    "user_id", flat=True
                )
            ),
            {self.staff.id, self.worker_two.id},
        )
        self.assertEqual(
            set(
                rows.filter(role=ExtraWorkAssignmentRole.MANAGER).values_list(
                    "user_id", flat=True
                )
            ),
            {self.manager.id},
        )

    def test_both_roles_across_several_requests(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._combined(
                [self.staff],
                [self.manager],
                requests=[self.request_a, self.request_b],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        # 2 requests x (1 worker + 1 manager)
        self.assertEqual(response.data["created"], 4)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 4)

    def test_an_ineligible_manager_rejects_the_workers_with_it(self):
        """The whole point of one request rather than two.

        `self.staff` is a perfectly good worker here. Naming a STAFF
        member as a MANAGER makes the manager group unresolvable, and
        the workers in the SAME body must not land — a client firing two
        requests would have created them and then failed.
        """
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._combined([self.staff], [self.worker_two]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_an_ineligible_worker_rejects_the_managers_with_it(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            self._combined([self.manager_two], [self.manager]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_a_foreign_id_and_a_fictional_id_answer_identically(self):
        """H-1. Compared for EQUALITY of the rendered body, not merely
        for both being 400 — two different 400s still answer "does this
        id name a real person"."""
        self.authenticate(self.company_admin)
        foreign = self.client.post(
            BULK_URL, self._combined([self.staff_b], [self.manager]), format="json"
        )
        fictional = self.client.post(
            BULK_URL,
            {
                "requests": [self.request_a.id],
                "workers": [999_999],
                "managers": [self.manager.id],
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fictional.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(foreign.data, fictional.data)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_reassigning_is_counted_not_an_error(self):
        self.authenticate(self.company_admin)
        body = self._combined([self.staff], [self.manager])
        self.client.post(BULK_URL, body, format="json")
        second = self.client.post(BULK_URL, body, format="json")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(second.data["already_assigned"], 2)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 2)

    def test_the_combined_shape_unassigns_both_roles(self):
        self.authenticate(self.company_admin)
        self.client.post(
            BULK_URL, self._combined([self.staff], [self.manager]), format="json"
        )
        response = self.client.post(
            BULK_URL,
            self._combined([self.staff], [self.manager], mode="unassign"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["removed"], 2)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_the_single_role_body_still_works(self):
        """The Sprint 157 shape is what the detail page's remove path
        speaks; changing shape under an existing caller would be a worse
        problem than accepting two."""
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL, self._body([self.request_a], [self.staff]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["created"], 1)
        self.assertEqual(
            ExtraWorkAssignment.objects.get().role,
            ExtraWorkAssignmentRole.WORKER,
        )

    def test_a_body_naming_nobody_is_rejected(self):
        self.authenticate(self.company_admin)
        response = self.client.post(
            BULK_URL,
            {"requests": [self.request_a.id], "workers": [], "managers": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)

    def test_a_customer_user_still_cannot_call_it(self):
        self.authenticate(self.customer_user)
        response = self.client.post(
            BULK_URL, self._combined([self.staff], [self.manager]), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(ExtraWorkAssignment.objects.count(), 0)
