"""Sprint 181 §1/§3 — the ticket is the authority for operational state.

An Extra Work carries its own status AND its spawned ticket carries one.
They are two copies of one fact, and `IN_PROGRESS -> COMPLETED` used to
be drivable by hand, which is how rows came to read COMPLETED against a
ticket that was still OPEN.

  §1  Once an Extra Work HAS a ticket, the two forward operational pairs
      are system-only. No role can type them; `allowed_next_statuses`
      stops offering them; the edge-recovery and cancel paths survive;
      an Extra Work with NO ticket keeps every manual transition.
  §3  The reconciliation command reports by default, repairs only when
      asked, and NEVER writes a status `ALLOWED_TRANSITIONS` forbids.
"""
from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.management import call_command

from extra_work.models import (
    ExtraWorkRequest,
    ExtraWorkStatus,
    ExtraWorkStatusHistory,
)
from extra_work.state_machine import (
    TransitionError,
    allowed_next_statuses,
    apply_transition,
)
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture
from tickets.models import Ticket, TicketStatus


class _Fixture(_InvoiceRunFixture):
    def _make_ew(self, status_value, **extra):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title=extra.pop("title", "Authority EW"),
            description="d",
            status=status_value,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            **extra,
        )

    def _add_ticket(self, ew, status_value=TicketStatus.OPEN, **extra):
        return Ticket.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Operational ticket",
            description="d",
            status=status_value,
            extra_work_request=ew,
            **extra,
        )


class ManualOperationalTransitionsAreClosedTests(_Fixture):
    def test_provider_cannot_hand_complete_an_extra_work_with_a_ticket(self):
        """The defect, in one test. The ticket is still OPEN; nobody may
        declare the work finished on the Extra Work row."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        self._add_ticket(ew, TicketStatus.OPEN)

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ew, self.super_admin, ExtraWorkStatus.COMPLETED)
        self.assertEqual(
            ctx.exception.code, "operational_status_follows_ticket"
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_provider_cannot_hand_start_an_extra_work_with_a_ticket(self):
        ew = self._make_ew(ExtraWorkStatus.CUSTOMER_APPROVED)
        self._add_ticket(ew, TicketStatus.OPEN)

        with self.assertRaises(TransitionError) as ctx:
            apply_transition(ew, self.admin, ExtraWorkStatus.IN_PROGRESS)
        self.assertEqual(
            ctx.exception.code, "operational_status_follows_ticket"
        )

    def test_the_gate_is_not_about_who_is_asking(self):
        """SUPER_ADMIN is refused too, and with the SAME code — this is
        not a permissions answer dressed up as one."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        self._add_ticket(ew, TicketStatus.OPEN)
        for actor in (self.super_admin, self.admin):
            with self.assertRaises(TransitionError) as ctx:
                apply_transition(ew, actor, ExtraWorkStatus.COMPLETED)
            self.assertEqual(
                ctx.exception.code, "operational_status_follows_ticket"
            )

    def test_buttons_are_withdrawn_not_just_the_endpoint(self):
        """`allowed_next_statuses` feeds the UI. If it still offered the
        status, the operator would get a button that 400s."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        self._add_ticket(ew, TicketStatus.OPEN)
        self.assertNotIn(
            ExtraWorkStatus.COMPLETED,
            allowed_next_statuses(self.super_admin, ew),
        )

    def test_ticketless_extra_work_keeps_its_manual_transitions(self):
        """Nothing to derive from, so the manual path is all there is."""
        ew = self._make_ew(ExtraWorkStatus.CUSTOMER_APPROVED)
        self.assertIn(
            ExtraWorkStatus.IN_PROGRESS,
            allowed_next_statuses(self.super_admin, ew),
        )
        apply_transition(ew, self.super_admin, ExtraWorkStatus.IN_PROGRESS)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_soft_deleted_ticket_does_not_close_the_door(self):
        """A deleted ticket is not something to derive from."""
        ew = self._make_ew(ExtraWorkStatus.CUSTOMER_APPROVED)
        ticket = self._add_ticket(ew, TicketStatus.OPEN)
        Ticket.objects.filter(pk=ticket.pk).update(
            deleted_at="2026-08-01T00:00:00Z"
        )
        apply_transition(ew, self.super_admin, ExtraWorkStatus.IN_PROGRESS)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_edge_recovery_survives(self):
        """COMPLETED -> IN_PROGRESS is a human correcting the record with
        a written reason. That is the opposite of silent drift, so §1
        deliberately leaves it open."""
        ew = self._make_ew(ExtraWorkStatus.COMPLETED)
        self._add_ticket(ew, TicketStatus.CLOSED)
        apply_transition(
            ew,
            self.super_admin,
            ExtraWorkStatus.IN_PROGRESS,
            is_override=True,
            override_reason="Customer reported the work was not finished.",
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_cancel_survives(self):
        """Cancelling is a decision about the job, not a claim about how
        far it got."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        self._add_ticket(ew, TicketStatus.OPEN)
        apply_transition(
            ew,
            self.super_admin,
            ExtraWorkStatus.CANCELLED,
            is_override=True,
            override_reason="Customer withdrew the order.",
        )
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CANCELLED)

    def test_the_auto_sync_hook_still_drives_both_pairs(self):
        """The whole point: the system may still do what the human may
        not. Driving the TICKET moves the Extra Work."""
        ew = self._make_ew(ExtraWorkStatus.CUSTOMER_APPROVED)
        ticket = self._add_ticket(ew, TicketStatus.OPEN)

        from tickets.state_machine import apply_transition as ticket_transition

        ticket_transition(ticket, self.super_admin, TicketStatus.IN_PROGRESS)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)


class ReconcileCommandTests(_Fixture):
    def _run(self, *args):
        out = StringIO()
        call_command("reconcile_extra_work_status", *args, stdout=out)
        return out.getvalue()

    def test_reports_the_defect_and_writes_nothing_by_default(self):
        ew = self._make_ew(ExtraWorkStatus.COMPLETED)
        self._add_ticket(ew, TicketStatus.OPEN)

        output = self._run()
        self.assertIn("REPAIRABLE", output)
        self.assertIn(str(ew.id), output)
        self.assertIn("would set", output)

        ew.refresh_from_db()
        self.assertEqual(
            ew.status,
            ExtraWorkStatus.COMPLETED,
            "the default run must not write",
        )

    def test_repair_walks_the_row_back_and_records_history(self):
        ew = self._make_ew(ExtraWorkStatus.COMPLETED)
        self._add_ticket(ew, TicketStatus.OPEN)
        before = ExtraWorkStatusHistory.objects.filter(
            extra_work=ew
        ).count()

        self._run("--repair")

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)
        self.assertGreater(
            ExtraWorkStatusHistory.objects.filter(extra_work=ew).count(),
            before,
            "a correction must leave a history row, not a silent update",
        )

    def test_understated_rows_are_reported_but_left_alone(self):
        """IN_PROGRESS against an untouched ticket. The derived value is
        CUSTOMER_APPROVED and no allowed transition reaches it, so the
        command reports and stops rather than inventing a pair."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        self._add_ticket(ew, TicketStatus.OPEN)

        output = self._run("--repair")
        self.assertIn("REPORT ONLY", output)
        self.assertIn("left alone", output)

        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.IN_PROGRESS)

    def test_agreeing_rows_are_not_listed(self):
        ew = self._make_ew(ExtraWorkStatus.COMPLETED)
        self._add_ticket(ew, TicketStatus.CLOSED)
        output = self._run()
        self.assertNotIn(f"  {ew.id:>6}  ", output)

    def test_ticketless_rows_are_never_touched(self):
        ew = self._make_ew(ExtraWorkStatus.COMPLETED)
        self._run("--repair")
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.COMPLETED)

    def test_cancelled_row_with_a_closed_ticket_is_not_a_contradiction(self):
        ew = self._make_ew(ExtraWorkStatus.CANCELLED)
        self._add_ticket(ew, TicketStatus.CLOSED)
        output = self._run("--repair")
        self.assertIn("UNEXPECTED", output)
        ew.refresh_from_db()
        self.assertEqual(ew.status, ExtraWorkStatus.CANCELLED)

    def test_repair_only_ever_writes_an_allowed_transition(self):
        """The rule that keeps this command from becoming the next source
        of drift. Every stored status the repair produces must be
        reachable from the one it replaced."""
        from extra_work.management.commands.reconcile_extra_work_status import (
            REPAIR_PATHS,
        )
        from extra_work.state_machine import ALLOWED_TRANSITIONS

        for (stored, _derived), hops in REPAIR_PATHS.items():
            current = stored
            for hop in hops:
                self.assertIn(
                    (current, hop),
                    ALLOWED_TRANSITIONS,
                    f"repair path {stored} -> {hops} walks the "
                    f"non-existent pair ({current}, {hop})",
                )
                current = hop
