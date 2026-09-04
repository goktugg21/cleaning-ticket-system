"""P-16 Part C — two extra-work API rules from the P-14 S4 list.

1. THE PLAN GATE ANSWERS AFTER PAIR-LEGALITY (the proposal refusal
   order). An impossible move — a CANCELLED proposal asked to SENT — is
   refused as `invalid_transition`, the true FIRST reason, never as
   `plan_requirements_unmet` (a plan problem the move would still have
   after fixing the plan). The gate still guards the LEGAL pair: a
   DRAFT proposal with an incomplete plan keeps its
   `plan_requirements_unmet` refusal.

2. THE CANCEL CARRIES ITS WHY. A CANCELLED transition without a written
   reason in any field (`note`, the `reason` alias, `override_reason`)
   is refused with `cancel_note_required`; the `reason` key — which the
   old serializer silently dropped — now lands as the note.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkCategory,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Proposal,
    ProposalStatus,
)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="P16C BV")
        cls.building = Building.objects.create(
            name="P16C Building", company=cls.company
        )
        cls.customer = Customer.objects.create(
            name="P16C Customer", company=cls.company
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="p16c-admin@osius.demo",
            password="x",
            role=UserRole.SUPER_ADMIN,
            full_name="P16C Admin",
        )

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _ew(self, *, status=ExtraWorkStatus.UNDER_REVIEW):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="P16C EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            created_by=self.admin,
        )


class ProposalRefusalOrderTests(_Base):
    def _proposal(self, ew, status):
        return Proposal.objects.create(
            extra_work_request=ew,
            status=status,
            created_by=self.admin,
        )

    def test_an_impossible_pair_answers_invalid_transition_first(self):
        """CANCELLED -> SENT on an UNPLANNED extra work: both reasons
        are true, but only one is the FIRST — fixing the plan would not
        make the move legal."""
        ew = self._ew()  # bare: all four plan requirements unmet
        proposal = self._proposal(ew, ProposalStatus.CANCELLED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "invalid_transition")

    def test_the_legal_pair_keeps_its_plan_gate(self):
        """DRAFT -> SENT with an incomplete plan: the gate still bites."""
        ew = self._ew()
        proposal = self._proposal(ew, ProposalStatus.DRAFT)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "plan_requirements_unmet")


class CancelNoteRequiredTests(_Base):
    def test_a_bare_cancel_is_refused_with_a_stable_code(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CANCELLED},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "cancel_note_required")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.REQUESTED)

    def test_a_blank_note_is_no_note(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.CANCELLED, "note": "   "},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "cancel_note_required")

    def test_a_note_lets_the_cancel_through_and_lands_on_history(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CANCELLED,
                "note": "Klant heeft de aanvraag ingetrokken",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = ExtraWorkStatusHistory.objects.filter(
            extra_work=ew, new_status=ExtraWorkStatus.CANCELLED
        ).latest("id")
        self.assertIn("ingetrokken", row.note)

    def test_the_reason_alias_is_no_longer_dropped(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {
                "to_status": ExtraWorkStatus.CANCELLED,
                "reason": "Dubbel aangemaakt",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = ExtraWorkStatusHistory.objects.filter(
            extra_work=ew, new_status=ExtraWorkStatus.CANCELLED
        ).latest("id")
        self.assertIn("Dubbel aangemaakt", row.note)

    def test_a_non_cancel_transition_still_needs_no_note(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
