"""P-15 — the BM's people picker answers like the validator (S2).

P-14's C1 finding (ticket 311, users 6/5/12): `GET /tickets/{id}/
assignments/candidates/?role=WORKER` returned `[]` for a
BUILDING_MANAGER while CA/SA got both eligible staff and the same BM's
direct `POST /staff-assignments/` succeeded — read and write disagreed
about eligibility (picker ⊂ validator, the Sprint 152.1 §1a class).

The cause: `eligible_users_for_building` narrowed every actor by
`manageable_user_ids_for`, which answers an EMPTY set for a BM (they
administer nobody) — but assignment eligibility is a BUILDING fact and
the write validators judge the target against the building alone. Now a
BM assigned to the building reads the raw building set; one who is not
assigned reads nothing.
"""
from __future__ import annotations

from rest_framework.test import APITestCase

from accounts.models import StaffProfile, UserRole
from buildings.models import BuildingStaffVisibility
from companies.models import CompanyUserMembership
from test_utils import TenantFixtureMixin


class BmCandidatesTests(TenantFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.worker1 = self.make_user("w1-cand@example.com", UserRole.STAFF)
        self.worker2 = self.make_user("w2-cand@example.com", UserRole.STAFF)
        for worker in (self.worker1, self.worker2):
            BuildingStaffVisibility.objects.create(
                user=worker, building=self.building
            )
            StaffProfile.objects.create(user=worker, is_active=True)
        # self.manager is a BM assigned to self.building (the fixture);
        # give them a company membership like real BMs hold.
        CompanyUserMembership.objects.create(
            user=self.manager, company=self.company
        )

    def _candidates(self, user, role="WORKER"):
        self.client.force_authenticate(user)
        return self.client.get(
            f"/api/tickets/{self.ticket.id}/assignments/candidates/",
            {"role": role},
        )

    def test_the_bm_reads_the_same_workers_the_admin_does(self):
        bm = self._candidates(self.manager)
        admin = self._candidates(self.company_admin)
        self.assertEqual(bm.status_code, 200, bm.data)
        self.assertEqual(admin.status_code, 200)
        bm_ids = {row["id"] for row in bm.data}
        admin_ids = {row["id"] for row in admin.data}
        self.assertEqual(bm_ids, admin_ids)
        self.assertIn(self.worker1.id, bm_ids)
        self.assertIn(self.worker2.id, bm_ids)

    def test_what_the_picker_offers_the_write_accepts(self):
        candidate_ids = {
            row["id"] for row in self._candidates(self.manager).data
        }
        self.assertIn(self.worker1.id, candidate_ids)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/staff-assignments/",
            {"user_id": self.worker1.id},
            format="json",
        )
        self.assertIn(response.status_code, (200, 201), response.data)

    def test_an_unassigned_bm_reads_nothing(self):
        """`other_manager` manages another building; this ticket is out
        of their scope entirely — a 404, never a roster."""
        response = self._candidates(self.other_manager)
        self.assertEqual(response.status_code, 404)
