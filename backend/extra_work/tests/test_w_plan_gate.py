"""W-PLAN — THE LAW: planning gates pricing; pricing gates operational.

The four requirements (>=1 WORKER, >=1 MANAGER, a committed start
date, planned hours > 0) bind at the three pricing doors:

    D1  POST /api/extra-work/<id>/proposals/           (create)
    D2  proposal transition -> SENT                    (send/start)
    D3  POST /api/extra-work/<id>/transition/ with
        to_status=PRICING_PROPOSED                     (workflow leg)

The one bypass is the recorded override: a non-blank `override_reason`
opens pricing AND writes an `is_override=True` history row. Task 3's
past-day lock on the plan write is covered here too, as is the Task 2
ticket-timeline annotation.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import User, UserRole
from buildings.models import Building
from companies.models import Company
from customers.models import Customer, CustomerBuildingMembership
from extra_work.models import (
    ExtraWorkAssignment,
    ExtraWorkAssignmentRole,
    ExtraWorkCategory,
    ExtraWorkPlannedHours,
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
    Proposal,
    ProposalStatus,
)
from extra_work.planning import (
    PLAN_REQ_HOURS,
    PLAN_REQ_MANAGER,
    PLAN_REQ_STAFF,
    PLAN_REQ_START_DATE,
    plan_requirements_unmet,
)

from .plan_gate_fixture import make_plan_complete


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="PlanGate BV")
        cls.building = Building.objects.create(
            name="PG Building", company=cls.company
        )
        cls.customer = Customer.objects.create(
            name="PG Customer", company=cls.company
        )
        CustomerBuildingMembership.objects.create(
            customer=cls.customer, building=cls.building
        )
        cls.admin = User.objects.create_user(
            email="plangate-admin@osius.demo",
            password="x",
            role=UserRole.SUPER_ADMIN,
            full_name="PlanGate Admin",
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
            title="Plan-gate EW",
            description="d",
            category=ExtraWorkCategory.DEEP_CLEANING,
            status=status,
            created_by=self.admin,
        )


class PlanRequirementTests(_Base):
    def test_all_four_unmet_on_a_bare_request(self):
        ew = self._ew()
        self.assertEqual(
            plan_requirements_unmet(ew),
            [
                PLAN_REQ_STAFF,
                PLAN_REQ_MANAGER,
                PLAN_REQ_START_DATE,
                PLAN_REQ_HOURS,
            ],
        )

    def test_fixture_satisfies_all_four(self):
        ew = make_plan_complete(self._ew())
        self.assertEqual(plan_requirements_unmet(ew), [])

    def test_distributed_hours_satisfy_without_budget(self):
        ew = self._ew()
        make_plan_complete(ew)
        ew.budget_hours = None
        ew.save(update_fields=["budget_hours"])
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=ew,
            user=self.admin,
            hours=Decimal("2.00"),
            set_by=self.admin,
        )
        self.assertEqual(plan_requirements_unmet(ew), [])


class D1CreateDoorTests(_Base):
    def test_unplanned_create_refused_with_named_requirements(self):
        ew = self._ew()
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "plan_requirements_unmet")
        self.assertEqual(
            resp.data["unmet"],
            [
                PLAN_REQ_STAFF,
                PLAN_REQ_MANAGER,
                PLAN_REQ_START_DATE,
                PLAN_REQ_HOURS,
            ],
        )
        # The full checklist rides along, satisfied ones included.
        self.assertEqual(len(resp.data["requirements"]), 4)
        self.assertFalse(Proposal.objects.filter(extra_work_request=ew).exists())

    def test_planned_create_succeeds(self):
        ew = make_plan_complete(self._ew())
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_partial_plan_names_only_the_missing(self):
        ew = self._ew()
        ExtraWorkAssignment.objects.create(
            extra_work_request=ew,
            user=self.admin,
            role=ExtraWorkAssignmentRole.WORKER,
            assigned_by=self.admin,
        )
        ew.provider_planned_date = timezone.localdate()
        ew.save(update_fields=["provider_planned_date"])
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.data["unmet"], [PLAN_REQ_MANAGER, PLAN_REQ_HOURS]
        )

    def test_override_reason_opens_pricing_and_writes_the_row(self):
        ew = self._ew()
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"override_reason": "Customer is on the phone; plan follows."},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        row = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew, is_override=True
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertIn("incomplete plan (override)", row.note)
        self.assertIn("plan_staff", row.note)

    def test_blank_override_reason_does_not_bypass(self):
        ew = self._ew()
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/",
            {"override_reason": "   "},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "plan_requirements_unmet")


class D2SendDoorTests(_Base):
    def test_send_of_a_pre_gate_draft_is_refused_unplanned(self):
        ew = self._ew()
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.DRAFT,
            created_by=self.admin,
        )
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "plan_requirements_unmet")

    def test_send_passes_once_planned(self):
        # The gate itself passes; the send may still trip the send-time
        # pricing validations (cart coverage etc.), which are NOT this
        # test's subject — so assert only that the refusal, if any, is
        # not the plan gate.
        ew = make_plan_complete(self._ew())
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.DRAFT,
            created_by=self.admin,
        )
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/proposals/{proposal.id}/transition/",
            {"to_status": ProposalStatus.SENT},
            format="json",
        )
        if resp.status_code == 400:
            self.assertNotEqual(
                resp.data.get("code"), "plan_requirements_unmet", resp.data
            )


class D3WorkflowLegTests(_Base):
    def test_direct_pricing_transition_refused_unplanned(self):
        ew = self._ew()
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "plan_requirements_unmet")

    def test_direct_pricing_transition_passes_once_planned(self):
        ew = make_plan_complete(self._ew())
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.PRICING_PROPOSED},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_other_transitions_do_not_ask_for_a_plan(self):
        ew = self._ew(status=ExtraWorkStatus.REQUESTED)
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/transition/",
            {"to_status": ExtraWorkStatus.UNDER_REVIEW},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)


class PastDayLockTests(_Base):
    def _plan_url(self, ew):
        return f"/api/extra-work/{ew.id}/plan/"

    def test_editing_a_past_day_without_reason_is_refused(self):
        ew = make_plan_complete(self._ew())
        yesterday = timezone.localdate() - timedelta(days=1)
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=ew,
            user=self.admin,
            date=yesterday,
            hours=Decimal("4.00"),
            set_by=self.admin,
        )
        resp = self._api(self.admin).post(
            self._plan_url(ew),
            {
                "start": False,
                "planned_hours": [
                    {
                        "user": self.admin.id,
                        "date": str(yesterday),
                        "hours": "6.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data["code"], "plan_past_day_locked")
        self.assertEqual(resp.data["days"], [str(yesterday)])
        row = ExtraWorkPlannedHours.objects.get(
            extra_work_request=ew, date=yesterday
        )
        self.assertEqual(row.hours, Decimal("4.00"))

    def test_identical_resubmit_of_a_past_row_is_free(self):
        ew = make_plan_complete(self._ew())
        yesterday = timezone.localdate() - timedelta(days=1)
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=ew,
            user=self.admin,
            date=yesterday,
            hours=Decimal("4.00"),
            set_by=self.admin,
        )
        resp = self._api(self.admin).post(
            self._plan_url(ew),
            {
                "start": False,
                "planned_hours": [
                    {
                        "user": self.admin.id,
                        "date": str(yesterday),
                        "hours": "4.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_override_reason_edits_the_past_and_records_it(self):
        ew = make_plan_complete(self._ew())
        yesterday = timezone.localdate() - timedelta(days=1)
        ExtraWorkPlannedHours.objects.create(
            extra_work_request=ew,
            user=self.admin,
            date=yesterday,
            hours=Decimal("4.00"),
            set_by=self.admin,
        )
        resp = self._api(self.admin).post(
            self._plan_url(ew),
            {
                "start": False,
                "past_days_override_reason": "Timesheet correction agreed.",
                "planned_hours": [
                    {
                        "user": self.admin.id,
                        "date": str(yesterday),
                        "hours": "6.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        row = ExtraWorkPlannedHours.objects.get(
            extra_work_request=ew, date=yesterday
        )
        self.assertEqual(row.hours, Decimal("6.00"))
        hist = (
            ExtraWorkStatusHistory.objects.filter(
                extra_work=ew, is_override=True
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(hist)
        self.assertIn("Timesheet correction agreed.", hist.note)

    def test_today_and_future_stay_free(self):
        ew = make_plan_complete(self._ew())
        today = timezone.localdate()
        resp = self._api(self.admin).post(
            self._plan_url(ew),
            {
                "start": False,
                "planned_hours": [
                    {"user": self.admin.id, "date": str(today), "hours": "3"},
                    {
                        "user": self.admin.id,
                        "date": str(today + timedelta(days=1)),
                        "hours": "5",
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)


class TicketTimelineAnnotationTests(_Base):
    def test_post_spawn_plan_change_lands_on_the_ticket_timeline(self):
        from tickets.models import Ticket, TicketStatus, TicketStatusHistory

        ew = make_plan_complete(
            self._ew(status=ExtraWorkStatus.IN_PROGRESS)
        )
        ticket = Ticket.objects.create(
            company=self.company,
            customer=self.customer,
            building=self.building,
            title="Spawned",
            description="d",
            status=TicketStatus.OPEN,
            created_by=self.admin,
            extra_work_request=ew,
        )
        resp = self._api(self.admin).post(
            f"/api/extra-work/{ew.id}/plan/",
            {"start": False, "budget_hours": "9.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        note_rows = TicketStatusHistory.objects.filter(
            ticket=ticket, note__startswith="Plan changed:"
        )
        self.assertEqual(note_rows.count(), 1)
        self.assertIn("budget 9.50h", note_rows.first().note)
