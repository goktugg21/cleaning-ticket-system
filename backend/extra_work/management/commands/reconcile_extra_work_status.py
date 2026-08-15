"""Sprint 181 §3 — find (and, when asked, repair) Extra Work rows whose
stored status disagrees with their operational ticket.

Sprint 181 §1 closes the door the drift came through: once an Extra Work
has a ticket, its operational status is derived and no human can type it.
That fixes the future. It does not fix the rows already on crmtest that
read COMPLETED against a ticket which is still OPEN, and those matter
beyond tidiness — `extra_work.billing.is_earned` reads the TICKET, so an
Extra Work claiming to be finished against an open ticket is not
invoiceable and nothing on screen says why.

REPORTS BY DEFAULT. `--repair` is the only thing that writes, and the
same table is printed first either way, so what changed is on the record.

The derivation mirrors `tickets.state_machine.
_sync_parent_extra_work_after_ticket_transition` exactly — the same two
rules the auto-sync hook applies, read as a snapshot instead of as an
event:

    all live tickets terminal (APPROVED / CLOSED)  -> COMPLETED
    every live ticket still OPEN                   -> CUSTOMER_APPROVED
    anything in between                            -> IN_PROGRESS

REPAIR ONLY EVER USES AN ALLOWED TRANSITION. That is the rule that keeps
this command from becoming the next source of drift: a repair that wrote
a status `ALLOWED_TRANSITIONS` forbids would be doing exactly what §1
just took away from operators. Where the derived value is not reachable
from the stored one, the row is reported and left alone — with the
reason printed, not swallowed.

In practice that splits the disagreements into two kinds:

  * OVERSTATED — the row claims more progress than its ticket supports
    (COMPLETED against an open ticket). Reachable, because
    `COMPLETED -> IN_PROGRESS` exists as the edge-recovery pair. These
    are repairable, and they are the defect the owner found.
  * UNDERSTATED — the row claims less than its ticket supports, or the
    correction would have to walk backwards through a pair that does
    not exist (IN_PROGRESS against a ticket nobody has picked up yet).
    Reported only. The prompt calls this shape mild and it is: nothing
    claims to be finished, so no money decision rests on it.

Deliberately NOT touched at all:
  * Extra Work with no live ticket. Nothing to derive from, which is the
    same reason §1 leaves those manual.
  * CANCELLED / CUSTOMER_REJECTED. Cancelling is a decision about the
    job, not a claim about how far it got.
  * Anything before CUSTOMER_APPROVED. An Extra Work cannot start
    operationally before its price is agreed, so a REQUESTED row with a
    ticket is a different and rarer defect; it is reported as UNEXPECTED
    rather than quietly rewritten.

Not run from a migration, by instruction and on merit: this rewrites
business status on live rows, and that belongs behind a human typing
`--repair` after reading the table.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from tickets.models import Ticket, TicketStatus

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from extra_work.state_machine import apply_transition


TERMINAL_TICKET_STATUSES = {TicketStatus.APPROVED, TicketStatus.CLOSED}

# Stored statuses this command will consider at all. Outside this set a
# disagreement is reported as UNEXPECTED and never rewritten.
RECONCILABLE_STATUSES = {
    ExtraWorkStatus.CUSTOMER_APPROVED,
    ExtraWorkStatus.IN_PROGRESS,
    ExtraWorkStatus.COMPLETED,
}

# (stored, derived) -> the hops to walk, every one of them a member of
# `extra_work.state_machine.ALLOWED_TRANSITIONS`. A pair absent from this
# map is reported and left alone; there is no fallback that writes a
# status the state machine does not admit.
#
# `COMPLETED -> CUSTOMER_APPROVED` maps to a single IN_PROGRESS hop on
# purpose: the state machine has no path back to CUSTOMER_APPROVED, and
# inventing one to make a report tidy would be worse than landing the row
# on the nearest true thing. IN_PROGRESS is not a lie — the work is not
# finished — and the printed table says the derived value was
# CUSTOMER_APPROVED, so nobody has to reverse-engineer the difference.
REPAIR_PATHS: dict[tuple[str, str], list[str]] = {
    (ExtraWorkStatus.COMPLETED, ExtraWorkStatus.IN_PROGRESS): [
        ExtraWorkStatus.IN_PROGRESS
    ],
    (ExtraWorkStatus.COMPLETED, ExtraWorkStatus.CUSTOMER_APPROVED): [
        ExtraWorkStatus.IN_PROGRESS
    ],
    (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.IN_PROGRESS): [
        ExtraWorkStatus.IN_PROGRESS
    ],
    (ExtraWorkStatus.CUSTOMER_APPROVED, ExtraWorkStatus.COMPLETED): [
        ExtraWorkStatus.IN_PROGRESS,
        ExtraWorkStatus.COMPLETED,
    ],
    (ExtraWorkStatus.IN_PROGRESS, ExtraWorkStatus.COMPLETED): [
        ExtraWorkStatus.COMPLETED
    ],
}

REPAIR_NOTE = (
    "Sprint 181 §3 reconciliation: stored status disagreed with the "
    "spawned ticket(s); corrected to the value the ticket implies."
)


def derive_status(ticket_statuses) -> str | None:
    """The operational status a set of live ticket statuses implies.

    Returns None when there is nothing to derive from (no tickets).
    """
    statuses = set(ticket_statuses)
    if not statuses:
        return None
    if statuses <= TERMINAL_TICKET_STATUSES:
        return ExtraWorkStatus.COMPLETED
    if statuses == {TicketStatus.OPEN}:
        return ExtraWorkStatus.CUSTOMER_APPROVED
    return ExtraWorkStatus.IN_PROGRESS


class Command(BaseCommand):
    help = (
        "Report Extra Work rows whose stored status disagrees with their "
        "operational ticket. Use --repair to correct the repairable ones."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help=(
                "Write the correction to the repairable rows. Without "
                "this flag the command only reports."
            ),
        )
        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help="Limit to one provider company id.",
        )

    def handle(self, *args, **options):
        repair = options["repair"]
        company_id = options["company"]

        qs = ExtraWorkRequest.objects.filter(deleted_at__isnull=True)
        if company_id is not None:
            qs = qs.filter(company_id=company_id)

        ew_rows = list(qs.only("id", "status", "title").order_by("id"))
        tickets_by_ew: dict[int, list] = {}
        for ticket in Ticket.objects.filter(
            extra_work_request_id__in=[e.id for e in ew_rows],
            deleted_at__isnull=True,
        ).only("id", "status", "ticket_no", "extra_work_request_id"):
            tickets_by_ew.setdefault(
                ticket.extra_work_request_id, []
            ).append(ticket)

        repairable, report_only, unexpected = [], [], []
        for ew in ew_rows:
            tickets = tickets_by_ew.get(ew.id, [])
            derived = derive_status([t.status for t in tickets])
            if derived is None or derived == ew.status:
                continue
            hops = REPAIR_PATHS.get((ew.status, derived))
            row = (ew, tickets, derived, hops)
            if ew.status not in RECONCILABLE_STATUSES:
                unexpected.append(row)
            elif hops is None:
                report_only.append(row)
            else:
                repairable.append(row)

        self._print_table(
            "REPAIRABLE - the row claims more progress than its ticket",
            repairable,
            total=len(ew_rows),
            repair=repair,
        )
        self._print_table(
            "REPORT ONLY - no allowed transition reaches the derived value",
            report_only,
            total=len(ew_rows),
            repair=False,
        )
        if unexpected:
            self._print_table(
                "UNEXPECTED - stored status is outside the operational "
                "segment",
                unexpected,
                total=len(ew_rows),
                repair=False,
            )

        if not repair:
            if repairable:
                self.stdout.write(
                    self.style.WARNING(
                        f"\nReport only. Re-run with --repair to write the "
                        f"{len(repairable)} correction(s) above."
                    )
                )
            return

        repaired, skipped = 0, []
        for ew, _tickets, _derived, hops in repairable:
            try:
                with transaction.atomic():
                    for hop in hops:
                        # `override_reason` on every hop, not only the
                        # backwards one: the state machine coerces
                        # `is_override` for the two operational override
                        # pairs and then demands a reason. Passing it
                        # unconditionally means a repair path can gain a
                        # hop later without silently starting to fail.
                        #
                        # Sprint 182 §5 — REASSIGN `ew`.
                        # `apply_transition` re-fetches the row with
                        # `select_for_update()`, mutates THAT instance
                        # and returns it; the caller's object is never
                        # touched. So hop 2 used to be computed from the
                        # ORIGINAL status: the one multi-hop path,
                        # CUSTOMER_APPROVED -> [IN_PROGRESS, COMPLETED],
                        # asked for (CUSTOMER_APPROVED, COMPLETED) on
                        # its second hop — not in ALLOWED_TRANSITIONS —
                        # so it raised `invalid_transition` and rolled
                        # the whole row back into `skipped`. It failed
                        # loudly and corrupted nothing, which is why
                        # nobody noticed; but the repair path the owner
                        # was told about could not run for that shape.
                        ew = apply_transition(
                            ew,
                            None,
                            hop,
                            note=REPAIR_NOTE,
                            override_reason=REPAIR_NOTE,
                        )
                repaired += 1
            except Exception as exc:  # noqa: BLE001 — reported, not hidden
                skipped.append((ew, exc))

        self.stdout.write(self.style.SUCCESS(f"\nRepaired {repaired} row(s)."))
        for ew, exc in skipped:
            self.stdout.write(
                self.style.ERROR(f"  EW #{ew.id}: could not repair - {exc}")
            )

    def _print_table(self, heading, rows, *, total, repair):
        self.stdout.write(
            f"\n{heading}: {len(rows)} of {total} Extra Work row(s)"
        )
        if not rows:
            return
        self.stdout.write(
            f"  {'EW':>6}  {'stored':<18} -> {'derived':<18} tickets"
        )
        for ew, tickets, derived, hops in rows:
            ticket_text = ", ".join(
                f"{t.ticket_no or f'#{t.id}'}={t.status}" for t in tickets
            )
            if hops is None:
                action = "left alone"
            elif hops[-1] != derived:
                action = (
                    "WILL SET" if repair else "would set"
                ) + f" {hops[-1]} (nearest reachable)"
            else:
                action = ("WILL SET" if repair else "would set") + f" {hops[-1]}"
            self.stdout.write(
                f"  {ew.id:>6}  {ew.status:<18} -> {derived:<18} "
                f"[{ticket_text}]  ({action})"
            )
