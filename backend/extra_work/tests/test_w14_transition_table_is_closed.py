"""W14 — the Extra Work transition table, written down and locked shut.

THE REPORT THIS ANSWERS. The owner: "from an OPEN extra work I pressed a
button and it went straight to COMPLETED with no steps in between." The
brief that followed said Extra Work has no state machine and one had to
be built, modelled on `tickets/state_machine.py`.

IT ALREADY HAS ONE. `extra_work/state_machine.py` carries an explicit
`ALLOWED_TRANSITIONS`, a per-transition role/scope resolver, entry
timestamps, an `ExtraWorkStatusHistory` row inside the same
`transaction.atomic`, `select_for_update` against a concurrent racer, and
reason-required override pairs. CLAUDE.md §3 has recorded it since
Sprint 26B. The jump the owner saw did not come from a missing table --
it came from a BUTTON that never consulted it (see
`frontend/src/components/extra-work/nextStep.ts`).

So the useful thing this file can do is not to build the table again. It
is to WRITE IT DOWN as an assertion, the way
`test_sprint28_proposal_state_machine.py` does for the PROPOSAL table,
which until now had that protection while the work's own table did not.
Two claims:

  1. The table IS this set of 15 pairs. A pair added or removed without
     touching this file fails here, and a widening is exactly the defect
     class the brief was worried about.
  2. EVERY other ordered pair of statuses is refused, by name. Not "we
     tested a few" -- all 41 of them, computed as the complement, so a
     status added to the enum tomorrow extends the sweep by itself.

Nothing here asserts role or scope; `test_sprint27a_rbac_safety_net` and
`test_sprint181_ticket_is_the_authority` own that layer.
"""
from __future__ import annotations

from decimal import Decimal
from itertools import permutations

from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from extra_work.state_machine import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    apply_transition,
)
from extra_work.tests.test_m4_billing_run import _InvoiceRunFixture


# The table, spelled out. Deliberately a literal and not a re-derivation:
# a test that computes the expected value the same way the code does
# cannot detect a change in either.
EXPECTED_TABLE: set[tuple[str, str]] = {
    # Customer-pricing loop (Sprint 26B).
    ("REQUESTED", "UNDER_REVIEW"),
    ("REQUESTED", "CANCELLED"),
    ("UNDER_REVIEW", "PRICING_PROPOSED"),
    ("UNDER_REVIEW", "CANCELLED"),
    ("PRICING_PROPOSED", "CUSTOMER_APPROVED"),
    ("PRICING_PROPOSED", "CUSTOMER_REJECTED"),
    ("PRICING_PROPOSED", "UNDER_REVIEW"),
    ("PRICING_PROPOSED", "CANCELLED"),
    ("CUSTOMER_REJECTED", "UNDER_REVIEW"),
    ("CUSTOMER_APPROVED", "CANCELLED"),
    # Instant route, system-only (Sprint 28 Batch 7).
    ("REQUESTED", "CUSTOMER_APPROVED"),
    # Operational segment (Sprint 29 Batch 29.8).
    ("CUSTOMER_APPROVED", "IN_PROGRESS"),
    ("IN_PROGRESS", "COMPLETED"),
    ("IN_PROGRESS", "CANCELLED"),
    # Edge recovery, reason required (Sprint 29 Batch 29.8).
    ("COMPLETED", "IN_PROGRESS"),
}


class TransitionTableTests(_InvoiceRunFixture):
    def _make_ew(self, status_value):
        return ExtraWorkRequest.objects.create(
            company=self.company,
            building=self.building,
            customer=self.customer,
            created_by=self.admin,
            title="Table probe",
            description="d",
            status=status_value,
            subtotal_amount=Decimal("100.00"),
            vat_amount=Decimal("21.00"),
            total_amount=Decimal("121.00"),
        )

    def test_table_is_exactly_the_fifteen_pairs_written_above(self):
        self.assertEqual(
            {(a, b) for (a, b) in ALLOWED_TRANSITIONS},
            EXPECTED_TABLE,
        )

    def test_no_status_reaches_completed_except_in_progress(self):
        """The owner's sentence, as an assertion. COMPLETED has exactly
        ONE way in, and it is not a shortcut from the start of the
        lifecycle."""
        into_completed = {
            frm for (frm, to) in ALLOWED_TRANSITIONS if to == "COMPLETED"
        }
        self.assertEqual(into_completed, {"IN_PROGRESS"})

    def test_every_pair_outside_the_table_is_refused_by_name(self):
        """The complement, swept. 8 statuses -> 56 ordered pairs; 15 are
        legal, so 41 must raise `invalid_transition`. Computed rather
        than listed so a new status is covered the day it is added."""
        statuses = [s.value for s in ExtraWorkStatus]
        refused = [
            pair
            for pair in permutations(statuses, 2)
            if pair not in ALLOWED_TRANSITIONS
        ]
        self.assertEqual(len(statuses), 8)
        self.assertEqual(len(refused), 41)

        for from_status, to_status in refused:
            ew = self._make_ew(from_status)
            with self.subTest(pair=f"{from_status}->{to_status}"):
                with self.assertRaises(TransitionError) as caught:
                    apply_transition(
                        ew,
                        self.admin,
                        to_status,
                        override_reason="probe",
                        is_override=True,
                    )
                self.assertEqual(caught.exception.code, "invalid_transition")
                ew.refresh_from_db()
                self.assertEqual(ew.status, from_status)

    def test_a_no_op_transition_is_refused_separately(self):
        """Same status to same status is not in the table either, but it
        earns its own code so a double-clicked button is not reported as
        a broken workflow."""
        ew = self._make_ew(ExtraWorkStatus.IN_PROGRESS)
        with self.assertRaises(TransitionError) as caught:
            apply_transition(ew, self.admin, ExtraWorkStatus.IN_PROGRESS)
        self.assertEqual(caught.exception.code, "no_op_transition")
