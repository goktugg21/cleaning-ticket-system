"""
Sprint 9B — operational scheduling + agenda filters on Ticket.

These tests pin:
  * the POST/DELETE /api/tickets/<pk>/schedule/ endpoint (set, reschedule,
    clear, terminal guard, validation, permissions, scope),
  * the additive agenda / scheduled_* filters on the ticket list,
  * SLA non-interference (scheduling never recomputes sla_*),
  * Extra Work -> ticket schedule seeding across all spawn paths,
  * the default list / stats / stats-by-building being unchanged.

`ExtraWorkRequestItem.requested_date` is a `DateField`;
`earliest_requested_start` seeds `scheduled_start_at` at local 00:00 of
the earliest requested date. The EW-propagation tests assert the spawned
ticket's `scheduled_start_at` equals
`make_aware(combine(earliest_date, time.min))`.
"""
import copy
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, UserRole
from buildings.models import (
    Building,
    BuildingManagerAssignment,
    BuildingStaffVisibility,
)
from companies.models import Company, CompanyUserMembership
from customers.models import (
    Customer,
    CustomerBuildingMembership,
    CustomerUserBuildingAccess,
    CustomerUserMembership,
)
from extra_work.instant_tickets import (
    earliest_requested_start,
    spawn_tickets_for_request,
)
from extra_work.models import (
    CustomerServicePrice,
    ExtraWorkRequest,
    ExtraWorkRequestItem,
    ExtraWorkRoutingDecision,
    Proposal,
    ProposalLine,
    ProposalStatus,
    Service,
    ServiceCategory,
)
from extra_work.proposal_tickets import spawn_tickets_for_proposal
from tickets.models import (
    Ticket,
    TicketScheduleStatus,
    TicketStatus,
    TicketStatusHistory,
)


def _schedule_url(ticket):
    return f"/api/tickets/{ticket.id}/schedule/"


class SchedulingBaseTest(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")
        self.building = Building.objects.create(
            company=self.company, name="B1"
        )
        self.other_building = Building.objects.create(
            company=self.company, name="B2"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust"
        )

        self.sa = User.objects.create_user(
            email="sa@osius.nl", password="x", role=UserRole.SUPER_ADMIN
        )
        self.ca = User.objects.create_user(
            email="ca@osius.nl", password="x", role=UserRole.COMPANY_ADMIN
        )
        CompanyUserMembership.objects.create(user=self.ca, company=self.company)
        self.bm = User.objects.create_user(
            email="bm@osius.nl", password="x", role=UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.bm, building=self.building
        )
        # A BM assigned only to the OTHER building (out of scope for B1).
        self.bm_other = User.objects.create_user(
            email="bm2@osius.nl", password="x", role=UserRole.BUILDING_MANAGER
        )
        BuildingManagerAssignment.objects.create(
            user=self.bm_other, building=self.other_building
        )

        self.staff = User.objects.create_user(
            email="staff@osius.nl", password="x", role=UserRole.STAFF
        )
        BuildingStaffVisibility.objects.create(
            user=self.staff, building=self.building
        )

        self.customer_user = User.objects.create_user(
            email="cu@osius.nl", password="x", role=UserRole.CUSTOMER_USER
        )
        membership = CustomerUserMembership.objects.create(
            user=self.customer_user, customer=self.customer
        )
        CustomerBuildingMembership.objects.create(
            customer=self.customer, building=self.building
        )
        CustomerUserBuildingAccess.objects.create(
            membership=membership, building=self.building
        )

        self.ticket = Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.sa,
            title="t",
            description="d",
            status=TicketStatus.OPEN,
        )

    def _auth(self, user):
        self.client.force_authenticate(user=user)


class ScheduleSetTest(SchedulingBaseTest):
    def test_set_schedule_persists_and_writes_history(self):
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=2)
        before = TicketStatusHistory.objects.filter(ticket=self.ticket).count()
        resp = self.client.post(
            _schedule_url(self.ticket),
            {
                "scheduled_start_at": start.isoformat(),
                "time_window_label": "morning",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.schedule_status, TicketScheduleStatus.SCHEDULED
        )
        self.assertIsNotNone(self.ticket.scheduled_start_at)
        self.assertEqual(self.ticket.time_window_label, "morning")
        self.assertIsNone(self.ticket.rescheduled_from)
        self.assertEqual(self.ticket.reschedule_reason, "")
        # Status unchanged.
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)
        # Exactly one annotation history row was written (old==new status).
        after = TicketStatusHistory.objects.filter(ticket=self.ticket).count()
        self.assertEqual(after, before + 1)
        row = TicketStatusHistory.objects.filter(ticket=self.ticket).latest(
            "created_at"
        )
        self.assertEqual(row.old_status, row.new_status)
        self.assertEqual(row.new_status, TicketStatus.OPEN)
        self.assertFalse(row.is_override)


class RescheduleTest(SchedulingBaseTest):
    def _set_initial(self):
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=2)
        self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": start.isoformat()},
            format="json",
        )
        self.ticket.refresh_from_db()
        return self.ticket.scheduled_start_at

    def test_reschedule_without_reason_400(self):
        self._set_initial()
        new_start = timezone.now() + timedelta(days=5)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": new_start.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get("code"), "reschedule_reason_required")

    def test_reschedule_with_reason(self):
        old_start = self._set_initial()
        new_start = timezone.now() + timedelta(days=6)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {
                "scheduled_start_at": new_start.isoformat(),
                "reschedule_reason": "customer requested later date",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.schedule_status, TicketScheduleStatus.RESCHEDULED
        )
        self.assertEqual(self.ticket.rescheduled_from, old_start)
        self.assertEqual(
            self.ticket.reschedule_reason, "customer requested later date"
        )


class ScheduleClearTest(SchedulingBaseTest):
    def test_clear_on_non_terminal(self):
        self._auth(self.bm)
        start = timezone.now() + timedelta(days=2)
        self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": start.isoformat(), "time_window_label": "am"},
            format="json",
        )
        resp = self.client.delete(_schedule_url(self.ticket))
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(
            self.ticket.schedule_status, TicketScheduleStatus.UNSCHEDULED
        )
        self.assertIsNone(self.ticket.scheduled_start_at)
        self.assertIsNone(self.ticket.scheduled_end_at)
        self.assertEqual(self.ticket.time_window_label, "")
        self.assertIsNone(self.ticket.rescheduled_from)
        self.assertEqual(self.ticket.reschedule_reason, "")


class ScheduleTerminalGuardTest(SchedulingBaseTest):
    def test_set_on_terminal_400(self):
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save(update_fields=["status"])
        self._auth(self.sa)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get("code"), "schedule_not_allowed_terminal")

    def test_clear_on_terminal_400(self):
        self.ticket.status = TicketStatus.CLOSED
        self.ticket.save(update_fields=["status"])
        self._auth(self.sa)
        resp = self.client.delete(_schedule_url(self.ticket))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data.get("code"), "schedule_not_allowed_terminal")


class ScheduleValidationTest(SchedulingBaseTest):
    def test_end_before_start_400(self):
        self._auth(self.sa)
        start = timezone.now() + timedelta(days=2)
        end = start - timedelta(hours=1)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {
                "scheduled_start_at": start.isoformat(),
                "scheduled_end_at": end.isoformat(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # ErrorDetail carries the stable code `schedule_invalid`.
        codes = []
        for v in resp.data.values():
            if isinstance(v, list):
                codes.extend(getattr(item, "code", None) for item in v)
            else:
                codes.append(getattr(v, "code", None))
        self.assertIn("schedule_invalid", codes)


class SchedulePermissionTest(SchedulingBaseTest):
    def test_sa_ca_bm_can_set(self):
        for user in (self.sa, self.ca, self.bm):
            t = Ticket.objects.create(
                company=self.company,
                building=self.building,
                customer=self.customer,
                created_by=self.sa,
                title="t",
                description="d",
            )
            self._auth(user)
            resp = self.client.post(
                _schedule_url(t),
                {"scheduled_start_at": (
                    timezone.now() + timedelta(days=1)
                ).isoformat()},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_staff_forbidden_for_role(self):
        self._auth(self.staff)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get("code"), "schedule_forbidden_for_role")

    def test_staff_can_read_agenda(self):
        # STAFF can still READ scheduled tickets via the list endpoint.
        self.ticket.scheduled_start_at = timezone.now() + timedelta(days=1)
        self.ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        self._auth(self.staff)
        resp = self.client.get("/api/tickets/", {"agenda": "upcoming"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in resp.data["results"]]
        self.assertIn(self.ticket.id, ids)

    def test_customer_user_forbidden(self):
        self._auth(self.customer_user)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data.get("code"), "schedule_forbidden_for_role")

    def test_out_of_scope_bm_404(self):
        # bm_other is assigned only to other_building; the ticket is in B1.
        # scope_tickets_for excludes it -> get_object 404 (role gate passes
        # first since bm_other IS a BUILDING_MANAGER).
        self._auth(self.bm_other)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": timezone.now().isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AgendaFilterTest(SchedulingBaseTest):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        # today
        self.t_today = Ticket.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.sa, title="today",
            description="d",
            scheduled_start_at=timezone.make_aware(
                datetime.combine(timezone.localdate(), time(9, 0))
            ),
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        # upcoming (future)
        self.t_upcoming = Ticket.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.sa, title="upcoming",
            description="d",
            scheduled_start_at=now + timedelta(days=3),
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        # overdue (past, non-terminal)
        self.t_overdue = Ticket.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.sa, title="overdue",
            description="d",
            scheduled_start_at=now - timedelta(days=3),
            schedule_status=TicketScheduleStatus.SCHEDULED,
            status=TicketStatus.IN_PROGRESS,
        )
        # past but terminal -> NOT overdue
        self.t_past_terminal = Ticket.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.sa, title="closed-past",
            description="d",
            scheduled_start_at=now - timedelta(days=4),
            schedule_status=TicketScheduleStatus.SCHEDULED,
            status=TicketStatus.CLOSED,
        )
        # unscheduled (the base self.ticket is unscheduled too)

    def _ids(self, resp):
        return [row["id"] for row in resp.data["results"]]

    def test_agenda_today(self):
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "today"})
        ids = self._ids(resp)
        self.assertIn(self.t_today.id, ids)
        self.assertNotIn(self.t_upcoming.id, ids)
        self.assertNotIn(self.t_overdue.id, ids)

    def test_agenda_upcoming(self):
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "upcoming"})
        ids = self._ids(resp)
        self.assertIn(self.t_upcoming.id, ids)
        self.assertNotIn(self.t_overdue.id, ids)
        self.assertNotIn(self.ticket.id, ids)  # unscheduled

    def test_agenda_overdue_excludes_terminal_and_future(self):
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "overdue"})
        ids = self._ids(resp)
        self.assertIn(self.t_overdue.id, ids)
        self.assertNotIn(self.t_past_terminal.id, ids)
        self.assertNotIn(self.t_upcoming.id, ids)

    def test_agenda_unscheduled(self):
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "unscheduled"})
        ids = self._ids(resp)
        self.assertIn(self.ticket.id, ids)
        self.assertNotIn(self.t_today.id, ids)

    def test_agenda_respects_scope(self):
        # BM only sees B1 scheduled tickets. Build a B2 scheduled ticket
        # the BM should never see in any agenda view.
        b2_ticket = Ticket.objects.create(
            company=self.company, building=self.other_building,
            customer=self.customer, created_by=self.sa, title="b2-upcoming",
            description="d",
            scheduled_start_at=timezone.now() + timedelta(days=2),
            schedule_status=TicketScheduleStatus.SCHEDULED,
        )
        self._auth(self.bm)
        resp = self.client.get("/api/tickets/", {"agenda": "upcoming"})
        ids = self._ids(resp)
        self.assertIn(self.t_upcoming.id, ids)
        self.assertNotIn(b2_ticket.id, ids)


class SlaNonInterferenceTest(SchedulingBaseTest):
    def test_scheduling_does_not_change_sla(self):
        self.ticket.refresh_from_db()
        sla_due_before = self.ticket.sla_due_at
        sla_status_before = self.ticket.sla_status

        self._auth(self.sa)
        future = timezone.now() + timedelta(days=10)
        resp = self.client.post(
            _schedule_url(self.ticket),
            {"scheduled_start_at": future.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.sla_due_at, sla_due_before)
        self.assertEqual(self.ticket.sla_status, sla_status_before)

    def test_future_scheduled_not_overdue(self):
        self.ticket.scheduled_start_at = timezone.now() + timedelta(days=5)
        self.ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "overdue"})
        ids = [row["id"] for row in resp.data["results"]]
        self.assertNotIn(self.ticket.id, ids)


class ExtraWorkSchedulePropagationTest(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Osius", slug="osius")
        self.building = Building.objects.create(
            company=self.company, name="B1"
        )
        self.customer = Customer.objects.create(
            company=self.company, name="Cust"
        )
        self.actor = User.objects.create_user(
            email="sa@osius.nl", password="x", role=UserRole.SUPER_ADMIN
        )
        self.category = ServiceCategory.objects.create(name="Cleaning")
        self.service = Service.objects.create(
            company=self.company,
            category=self.category,
            name="Window Cleaning",
            default_unit_price="100.00",
        )

    @staticmethod
    def _expected_seed(requested_date):
        return timezone.make_aware(
            datetime.combine(requested_date, time.min)
        )

    def test_direct_instant_spawn_carries_schedule(self):
        CustomerServicePrice.objects.create(
            customer=self.customer,
            service=self.service,
            unit_price=Decimal("90.00"),
            valid_from=date.today() - timedelta(days=30),
        )
        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.actor,
            title="EW", description="d",
            routing_decision=ExtraWorkRoutingDecision.INSTANT,
        )
        earliest = date.today() + timedelta(days=3)
        later = date.today() + timedelta(days=8)
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew, service=self.service,
            quantity=Decimal("1.00"), requested_date=later,
        )
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew, service=self.service,
            quantity=Decimal("1.00"), requested_date=earliest,
        )
        tickets = spawn_tickets_for_request(ew, actor=self.actor)
        self.assertEqual(len(tickets), 1)
        t = tickets[0]
        self.assertEqual(t.schedule_status, TicketScheduleStatus.SCHEDULED)
        self.assertEqual(t.scheduled_start_at, self._expected_seed(earliest))

    def test_proposal_spawn_carries_schedule_from_cart(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.actor,
            title="EW", description="d",
        )
        earliest = date.today() + timedelta(days=4)
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew, service=self.service,
            quantity=Decimal("1.00"), requested_date=earliest,
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.CUSTOMER_APPROVED,
            created_by=self.actor,
        )
        ProposalLine.objects.create(
            proposal=proposal, description="Ad-hoc line",
            quantity=Decimal("1.00"), unit_price=Decimal("50.00"),
            is_approved_for_spawn=True,
        )
        tickets = spawn_tickets_for_proposal(proposal, actor=self.actor)
        self.assertEqual(len(tickets), 1)
        t = tickets[0]
        self.assertEqual(t.schedule_status, TicketScheduleStatus.SCHEDULED)
        self.assertEqual(t.scheduled_start_at, self._expected_seed(earliest))

    def test_auto_start_pricing_send_spawn_carries_schedule(self):
        # AUTO_START / proposal-send lands in the same proposal spawn
        # helper; assert seeding works when the proposal is created in
        # the CUSTOMER_APPROVED state and spawned.
        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.actor,
            title="EW-auto", description="d",
        )
        earliest = date.today() + timedelta(days=2)
        ExtraWorkRequestItem.objects.create(
            extra_work_request=ew, service=self.service,
            quantity=Decimal("2.00"), requested_date=earliest,
        )
        proposal = Proposal.objects.create(
            extra_work_request=ew,
            status=ProposalStatus.CUSTOMER_APPROVED,
            created_by=self.actor,
        )
        ProposalLine.objects.create(
            proposal=proposal, service=self.service,
            quantity=Decimal("2.00"), unit_price=Decimal("50.00"),
            is_approved_for_spawn=True,
        )
        tickets = spawn_tickets_for_proposal(proposal, actor=self.actor)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(
            tickets[0].scheduled_start_at, self._expected_seed(earliest)
        )

    def test_seed_none_when_no_dated_line(self):
        ew = ExtraWorkRequest.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.actor,
            title="EW", description="d",
        )
        self.assertIsNone(earliest_requested_start(ew))


class ConvertedSourceTicketAgendaTest(SchedulingBaseTest):
    def test_converted_source_ticket_excluded_from_agenda(self):
        # Sprint 9B item 12 (agenda half): a source ticket driven to the
        # terminal CONVERTED_TO_EXTRA_WORK status must not appear in any
        # non-terminal agenda view, even when it carries a past schedule.
        # The seeding half of item 12 is covered by the spawn-helper
        # tests above (the convert flow spawns through the SAME
        # `spawn_tickets_for_request` helper).
        source = Ticket.objects.create(
            company=self.company, building=self.building,
            customer=self.customer, created_by=self.sa,
            title="src", description="d",
            scheduled_start_at=timezone.now() - timedelta(days=2),
            schedule_status=TicketScheduleStatus.SCHEDULED,
            status=TicketStatus.CONVERTED_TO_EXTRA_WORK,
        )
        self._auth(self.sa)
        resp = self.client.get("/api/tickets/", {"agenda": "overdue"})
        ids = [row["id"] for row in resp.data["results"]]
        self.assertNotIn(source.id, ids)


class DefaultListAndStatsUnchangedTest(SchedulingBaseTest):
    @staticmethod
    def _stats_invariants(data):
        # The `by_status` / `by_priority` dicts are intentionally SPARSE
        # (a values()/Count groupby only emits present statuses). We snap
        # the stable aggregates + the present-count dicts, which is what
        # "stats unchanged" means: the scheduling axis adds no ticket and
        # changes no status.
        return {
            "total": data["total"],
            "my_open": data["my_open"],
            "waiting_customer_approval": data["waiting_customer_approval"],
            "urgent": data["urgent"],
            "by_status": dict(data["by_status"]),
            "by_priority": dict(data["by_priority"]),
        }

    def test_default_list_unchanged_with_scheduled_ticket(self):
        self._auth(self.sa)
        baseline = self.client.get("/api/tickets/").data["count"]
        # Schedule the existing ticket; the default list count must not
        # change (scheduling is additive, not a filter by default).
        self.ticket.scheduled_start_at = timezone.now() + timedelta(days=1)
        self.ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        after = self.client.get("/api/tickets/").data["count"]
        self.assertEqual(baseline, after)

    def test_stats_unchanged(self):
        self._auth(self.sa)
        before = self._stats_invariants(
            self.client.get("/api/tickets/stats/").data
        )
        self.ticket.scheduled_start_at = timezone.now() + timedelta(days=1)
        self.ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        after = self._stats_invariants(
            self.client.get("/api/tickets/stats/").data
        )
        self.assertEqual(before, after)

    def test_stats_by_building_unchanged(self):
        self._auth(self.sa)
        before = copy.deepcopy(
            self.client.get("/api/tickets/stats/by-building/").data
        )
        self.ticket.scheduled_start_at = timezone.now() + timedelta(days=1)
        self.ticket.schedule_status = TicketScheduleStatus.SCHEDULED
        self.ticket.save(
            update_fields=["scheduled_start_at", "schedule_status"]
        )
        after = copy.deepcopy(
            self.client.get("/api/tickets/stats/by-building/").data
        )
        self.assertEqual(before, after)
