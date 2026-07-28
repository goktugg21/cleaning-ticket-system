"""
Sprint 132 — invoice grouping by Customer + Building + Department + Work
Type (PER_BUILDING_DEPARTMENT_WORK_TYPE), one level finer than Sprint
124's PER_BUILDING.

Covers:
  * grouping count/split for a mixed set (two buildings x two departments
    x two work types + untagged), deterministic order;
  * the untagged bucket gets its OWN invoice, never dropped/folded;
  * existing CUSTOMER / PER_BUILDING behaviour is unchanged — proven by
    the fact that the full pre-existing invoicing suite (174 tests) still
    passes unmodified, not re-asserted here;
  * the label ("<department> - <work type>") in all four shapes, via the
    serializer fields and the PDF;
  * reversal mirrors department/work_type onto the counter-invoice;
  * draft-delete releases the claim for this granularity too;
  * the Sprint 127.2 lock interaction: an EW relabelled during the DRAFT
    window can make the invoice's frozen department/work_type stale —
    `issue_invoice` must re-sync (or null out on disagreement) before the
    invoice becomes immutable.

Every invoice is built through `generate_draft_invoices` / `issue_invoice`
/ `reverse_invoice` / `delete_draft_invoice` — never by hand-setting
`status`.
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from customers.models import Customer
from extra_work.label_validation import (
    issued_invoice_locking_labels,
    validate_labels_for_customer,
)
from invoicing.selectors import unbilled_extra_work
from invoicing.serializers import InvoiceSerializer
from invoicing.services import delete_draft_invoice, generate_draft_invoices
from invoicing.state_machine import issue_invoice, reverse_invoice, send_invoice

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5
GRANULARITY = Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_WORK_TYPE


class GroupingTests(InvoicingFixture):
    def test_mixed_set_splits_by_building_department_work_type(self):
        # 2 buildings x 2 departments x 2 work types = 8 tagged combos,
        # one EW each, plus 2 untagged EW (one per building).
        for building in (self.building, self.building2):
            for dept in (self.dept_a, self.dept_b):
                for wt in (self.wt_a, self.wt_b):
                    self.make_ew(
                        closed_at=dt(2026, 5, 31),
                        building=building,
                        department=dept,
                        work_type=wt,
                    )
            self.make_ew(closed_at=dt(2026, 5, 31), building=building)

        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=GRANULARITY,
        )
        # 8 tagged combos + 2 untagged (one per building) = 10 invoices.
        self.assertEqual(len(created), 10)
        for inv in created:
            self.assertEqual(inv.lines.count(), 1)  # one EW per combo here

        keys = {
            (inv.building_id, inv.department_id, inv.work_type_id)
            for inv in created
        }
        expected = {
            (b.id, d.id, w.id)
            for b in (self.building, self.building2)
            for d in (self.dept_a, self.dept_b)
            for w in (self.wt_a, self.wt_b)
        } | {
            (self.building.id, None, None),
            (self.building2.id, None, None),
        }
        self.assertEqual(keys, expected)

    def test_untagged_not_dropped_not_folded(self):
        # Only untagged work in this period.
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)

        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(len(created), 1)
        inv = created[0]
        self.assertIsNone(inv.department_id)
        self.assertIsNone(inv.work_type_id)
        self.assertEqual(inv.lines.count(), 2)  # both EW, not dropped
        self.assertEqual(inv.total_amount, Decimal("242.00"))

    def test_partial_tagging_department_only_and_work_type_only(self):
        self.make_ew(
            closed_at=dt(2026, 5, 31), building=self.building, department=self.dept_a
        )
        self.make_ew(
            closed_at=dt(2026, 5, 31), building=self.building, work_type=self.wt_a
        )

        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(len(created), 2)
        keys = {(inv.department_id, inv.work_type_id) for inv in created}
        self.assertEqual(keys, {(self.dept_a.id, None), (None, self.wt_a.id)})

    def test_deterministic_order_building_then_department_then_work_type(self):
        # Created deliberately out of order.
        self.make_ew(
            closed_at=dt(2026, 5, 31),
            building=self.building2,
            department=self.dept_b,
            work_type=self.wt_b,
        )
        self.make_ew(closed_at=dt(2026, 5, 31), building=self.building)  # untagged
        self.make_ew(
            closed_at=dt(2026, 5, 31),
            building=self.building,
            department=self.dept_a,
            work_type=self.wt_a,
        )
        self.make_ew(
            closed_at=dt(2026, 5, 31),
            building=self.building,
            department=self.dept_b,
            work_type=self.wt_a,
        )

        created = generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=GRANULARITY,
        )
        keys = [(inv.building_id, inv.department_id, inv.work_type_id) for inv in created]
        # building1 (untagged first, then dept_a, then dept_b) before building2.
        self.assertEqual(
            keys,
            [
                (self.building.id, None, None),
                (self.building.id, self.dept_a.id, self.wt_a.id),
                (self.building.id, self.dept_b.id, self.wt_a.id),
                (self.building2.id, self.dept_b.id, self.wt_b.id),
            ],
        )

    def test_claims_and_idempotent(self):
        ew = self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        first = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(len(first), 1)
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

        second = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(second, [])

    def test_granularity_defaults_from_customer(self):
        self.customer.invoice_granularity_default = GRANULARITY
        self.customer.save(update_fields=["invoice_granularity_default"])
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_b, work_type=self.wt_b
        )
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(created), 2)


class DeleteReleasesClaimTests(InvoicingFixture):
    def test_delete_releases_ew_back_to_unbilled(self):
        ew = self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        ew.refresh_from_db()
        self.assertTrue(ew.is_invoiced)

        delete_draft_invoice(self.admin, inv)

        ew.refresh_from_db()
        self.assertFalse(ew.is_invoiced)
        self.assertIsNone(ew.invoiced_at)
        # Regeneration picks it back up.
        created2 = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(len(created2), 1)
        self.assertEqual(created2[0].department_id, self.dept_a.id)


class ReversalCopiesGroupLabelsTests(InvoicingFixture):
    def test_reversal_mirrors_department_and_work_type(self):
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        issued = issue_invoice(self.admin, inv)
        sent = send_invoice(self.admin, issued)

        reversal = reverse_invoice(self.admin, sent)
        self.assertEqual(reversal.department_id, self.dept_a.id)
        self.assertEqual(reversal.work_type_id, self.wt_a.id)
        # The release still works for this granularity too.
        released = unbilled_extra_work(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH
        )
        self.assertEqual(len(released), 1)


class LabelRenderingTests(InvoicingFixture):
    """The "<department> - <work type>" label in all four shapes, via the
    provider serializer (the frontend's `formatInvoiceGroupLabel` composes
    the exact same two fields — there is no frontend test runner yet, so
    this is the closest verifiable proxy) and the PDF."""

    def _invoice(self, *, department=None, work_type=None):
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=department, work_type=work_type
        )
        return generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]

    def test_both_set(self):
        inv = self._invoice(department=self.dept_a, work_type=self.wt_a)
        data = InvoiceSerializer(inv).data
        self.assertEqual(data["department_name"], "Dept A")
        self.assertEqual(data["work_type_name"], "WT A")

    def test_department_only(self):
        inv = self._invoice(department=self.dept_a)
        data = InvoiceSerializer(inv).data
        self.assertEqual(data["department_name"], "Dept A")
        self.assertIsNone(data["work_type_name"])

    def test_work_type_only(self):
        inv = self._invoice(work_type=self.wt_a)
        data = InvoiceSerializer(inv).data
        self.assertIsNone(data["department_name"])
        self.assertEqual(data["work_type_name"], "WT A")

    def test_neither_set(self):
        inv = self._invoice()
        data = InvoiceSerializer(inv).data
        self.assertIsNone(data["department_name"])
        self.assertIsNone(data["work_type_name"])

    def test_pdf_shows_row_when_labelled_and_omits_when_not(self):
        from pypdf import PdfReader

        from invoicing.invoice_pdf import render_invoice_pdf

        labelled = self._invoice(department=self.dept_a, work_type=self.wt_a)
        pdf_bytes = render_invoice_pdf(labelled)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        self.assertIn("Afdeling:", text)
        self.assertIn("Dept A - WT A", text)

        unlabelled = self._invoice()
        pdf_bytes = render_invoice_pdf(unlabelled)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        self.assertNotIn("Afdeling:", text)


class IssueResyncsGroupLabelsTests(InvoicingFixture):
    """The Sprint 127.2 lock interaction (sprint brief §5): generate a
    draft at the new granularity -> relabel one of its EWs (still allowed
    — the lock only bites once ISSUED) -> issue. The invoice's own
    department/work_type must reflect what its lines ACTUALLY carry at
    the moment it becomes immutable, not what was true at generation."""

    def test_relabel_to_same_department_is_a_no_op(self):
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        self.assertEqual(inv.department_id, self.dept_a.id)

        issued = issue_invoice(self.admin, inv)
        self.assertEqual(issued.department_id, self.dept_a.id)
        self.assertEqual(issued.work_type_id, self.wt_a.id)

    def test_relabel_before_issue_resyncs_single_line_invoice(self):
        ew = self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        self.assertEqual(inv.department_id, self.dept_a.id)

        # Still DRAFT -> still allowed (the Sprint 127.2 lock only bites
        # once ISSUED). Relabel directly (mirrors the validated write path
        # without going through the HTTP relabel action).
        validate_labels_for_customer(
            ew.customer, department=self.dept_b, work_type=self.wt_b
        )
        ew.department = self.dept_b
        ew.work_type = self.wt_b
        ew.save(update_fields=["department", "work_type", "updated_at"])

        # BEFORE this fix, the invoice would still show dept_a/wt_a here.
        issued = issue_invoice(self.admin, inv)
        self.assertEqual(issued.department_id, self.dept_b.id)
        self.assertEqual(issued.work_type_id, self.wt_b.id)

    def test_relabel_making_lines_disagree_nulls_the_invoice_axis(self):
        ew1 = self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        # Both EW land in the SAME (building, dept_a, wt_a) bucket -> one
        # invoice with two lines.
        created = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )
        self.assertEqual(len(created), 1)
        inv = created[0]
        self.assertEqual(inv.lines.count(), 2)
        self.assertEqual(inv.department_id, self.dept_a.id)

        # Relabel ONLY ew1's work_type while still DRAFT -> the invoice's
        # two lines now disagree on work_type (ew1=wt_b, ew2=wt_a).
        validate_labels_for_customer(ew1.customer, work_type=self.wt_b)
        ew1.work_type = self.wt_b
        ew1.save(update_fields=["work_type", "updated_at"])

        issued = issue_invoice(self.admin, inv)
        # department still agrees (both dept_a) -> kept.
        self.assertEqual(issued.department_id, self.dept_a.id)
        # work_type disagrees -> nulled, NOT left stale at either value.
        self.assertIsNone(issued.work_type_id)

    def test_customer_granularity_invoice_never_gains_a_label(self):
        # A CUSTOMER-granularity invoice never claimed a department/
        # work_type grouping — even if (by coincidence) every one of its
        # lines happens to share one, issuing it must NOT retroactively
        # invent a label it was never generated with.
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )[0]
        self.assertIsNone(inv.department_id)

        issued = issue_invoice(self.admin, inv)
        self.assertIsNone(issued.department_id)
        self.assertIsNone(issued.work_type_id)

    def test_untagged_label_granularity_invoice_resyncs_a_new_label(self):
        # Sprint 134 — the gap the early-return used to miss: an UNTAGGED
        # PER_BUILDING_DEPARTMENT_WORK_TYPE invoice has department_id and
        # work_type_id both NULL at generation, exactly like a CUSTOMER/
        # PER_BUILDING invoice's own "never claimed a label" NULLs — before
        # this fix, the FK-only check treated them the same and this
        # invoice never resynced. `granularity` disambiguates them: this
        # one DID claim a grouping (the untagged bucket), so it must still
        # pick up a label if its EW gets tagged during the draft window.
        ew = self.make_ew(closed_at=dt(2026, 5, 31))  # no department/work_type
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        self.assertIsNone(inv.department_id)
        self.assertIsNone(inv.work_type_id)
        self.assertEqual(inv.granularity, GRANULARITY)

        # Still DRAFT -> still allowed. Tag the previously-untagged EW.
        validate_labels_for_customer(
            ew.customer, department=self.dept_a, work_type=self.wt_a
        )
        ew.department = self.dept_a
        ew.work_type = self.wt_a
        ew.save(update_fields=["department", "work_type", "updated_at"])

        # BEFORE this fix, the invoice would still show NULL/NULL here —
        # silently disagreeing with the by-department report, which groups
        # this EW under dept_a/wt_a now that it's tagged.
        issued = issue_invoice(self.admin, inv)
        self.assertEqual(issued.department_id, self.dept_a.id)
        self.assertEqual(issued.work_type_id, self.wt_a.id)

    def test_locked_after_issue_relabel_rejected(self):
        # Confirms the OTHER half of the sequence in the brief: once
        # ISSUED, the EW's labels are locked (pre-existing Sprint 127.2
        # behaviour) — proving the resync fix above runs at exactly the
        # right moment (before the lock bites), not after.
        ew = self.make_ew(
            closed_at=dt(2026, 5, 31), department=self.dept_a, work_type=self.wt_a
        )
        inv = generate_draft_invoices(
            self.admin, self.company.id, self.customer.id, YEAR, MONTH,
            granularity=GRANULARITY,
        )[0]
        issue_invoice(self.admin, inv)

        ew.refresh_from_db()
        self.assertIsNotNone(issued_invoice_locking_labels(ew))
