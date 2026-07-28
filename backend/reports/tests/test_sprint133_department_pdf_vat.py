"""
Sprint 133 — the department PDF mixed two VAT bases in one table: detail
rows rendered `subtotal` (ex-VAT, matching the "Excl. BTW" column header),
but every work-type row, subtotal, department total and building total in
BOTH the summary and detail sections rendered `total` (inc-VAT) instead —
so a group's own rows never summed to the figure printed beneath them.

Fixed by rendering `subtotal` everywhere except the top headline, which
now shows all three figures explicitly (Excl. BTW / BTW / Incl. BTW) so
the inc-VAT total is not lost from the document.

These tests lock the ARITHMETIC property that was broken — a subtotal
line must equal the sum of the rows it summarizes — and that the summary
and detail sections, which read the same payload through two separate
rendering loops (`build_extra_work_by_department_pdf`'s two `for building
in buildings` loops), report the identical figure for the same group.
Every EW here carries real (non-zero) VAT so subtotal != total and the
bug is actually observable — a zero-VAT fixture would pass either way.
"""
import re
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader
from rest_framework import status

from customers.models import WorkType
from extra_work.models import ExtraWorkStatus
from tickets.models import TicketStatus

from .test_sprint131_extra_work_by_department import URL_DEPT_PDF, _DeptReportBase


def _nl_to_decimal(text: str) -> Decimal:
    """Inverse of the PDF's `_nl_number`: "1.282,81" -> Decimal("1282.81")."""
    return Decimal(text.replace(".", "").replace(",", "."))


def _line_money(text: str, label: str) -> Decimal:
    """The money figure on the line "<label> <count> € <amount>"."""
    m = re.search(re.escape(label) + r"\s+\d+\s+€\s*([\d.,]+)", text)
    assert m, f"{label!r} not found in:\n{text}"
    return _nl_to_decimal(m.group(1))


def _row_money(text: str, title: str) -> Decimal:
    """The money figure on a detail row's own line, keyed by its title."""
    m = re.search(r"\b" + re.escape(title) + r"\b.*?€\s*([\d.,]+)", text)
    assert m, f"row {title!r} not found in:\n{text}"
    return _nl_to_decimal(m.group(1))


class DepartmentPDFVatArithmeticTests(_DeptReportBase):
    """One building, two departments: Algemeen (two work types, one of them
    with two rows) and Event (one work type, one row) — enough nesting to
    check the arithmetic at the work-type, department AND building level."""

    def setUp(self):
        super().setUp()
        self.wt_move = WorkType.objects.create(
            customer=self.customer, name="Verhuizing"
        )
        self._row("Row A", "100.00", "21.00", "121.00", self.dept_general, self.wt_clean)
        self._row("Row B", "50.00", "10.50", "60.50", self.dept_general, self.wt_clean)
        self._row("Row C", "30.00", "6.30", "36.30", self.dept_general, self.wt_repair)
        self._row("Row D", "40.00", "8.40", "48.40", self.dept_event, self.wt_move)

    def _row(self, title, subtotal, vat, total, department, work_type):
        ew = self._ew(
            self.company,
            self.building,
            self.customer,
            subtotal=subtotal,
            vat=vat,
            total=total,
            final_subtotal=subtotal,
            final_vat=vat,
            final_total=total,
            ew_status=ExtraWorkStatus.CUSTOMER_APPROVED,
            department=department,
            work_type=work_type,
            title=title,
        )
        self._spawn(ew, TicketStatus.CLOSED)
        return ew

    def _pdf_text(self):
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(URL_DEPT_PDF, {"customer": self.customer.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reader = PdfReader(BytesIO(response.content))
        summary_text = reader.pages[0].extract_text()
        detail_text = "\n".join(p.extract_text() for p in reader.pages[1:])
        return summary_text, detail_text

    def test_detail_subtotal_equals_sum_of_its_rows(self):
        _, detail_text = self._pdf_text()
        row_a = _row_money(detail_text, "Row A")
        row_b = _row_money(detail_text, "Row B")
        self.assertEqual(row_a, Decimal("100.00"))
        self.assertEqual(row_b, Decimal("50.00"))

        wt_subtotal = _line_money(detail_text, "Subtotaal Eindschoonmaak")
        # This is exactly the property that was broken: before the fix this
        # line rendered € 181,50 (the sum of the rows' inc-VAT `total`), not
        # the sum of the ex-VAT amounts actually printed above it.
        self.assertEqual(wt_subtotal, row_a + row_b)
        self.assertEqual(wt_subtotal, Decimal("150.00"))

    def test_department_and_building_totals_are_ex_vat_and_sum_correctly(self):
        _, detail_text = self._pdf_text()
        dept_subtotal = _line_money(detail_text, "Subtotaal Algemeen")
        # Algemeen = Eindschoonmaak (150.00) + Reparatie (30.00).
        self.assertEqual(dept_subtotal, Decimal("180.00"))

        building_total = _line_money(detail_text, "Totaal gebouw")
        # Building A = Algemeen (180.00) + Event (40.00).
        self.assertEqual(building_total, Decimal("220.00"))

    def test_summary_and_detail_agree_on_the_same_group(self):
        """The two sections read the same payload through two separate
        rendering loops and currently agree only by accident — lock it."""
        summary_text, detail_text = self._pdf_text()

        summary_wt = _line_money(summary_text, "Eindschoonmaak")
        detail_wt = _line_money(detail_text, "Subtotaal Eindschoonmaak")
        self.assertEqual(summary_wt, detail_wt)
        self.assertEqual(summary_wt, Decimal("150.00"))

        summary_dept = _line_money(summary_text, "Subtotaal Algemeen")
        detail_dept = _line_money(detail_text, "Subtotaal Algemeen")
        self.assertEqual(summary_dept, detail_dept)
        self.assertEqual(summary_dept, Decimal("180.00"))

        summary_building = _line_money(summary_text, "Totaal gebouw")
        detail_building = _line_money(detail_text, "Totaal gebouw")
        self.assertEqual(summary_building, detail_building)
        self.assertEqual(summary_building, Decimal("220.00"))

    def test_headline_shows_all_three_figures_and_ex_vat_note(self):
        summary_text, _ = self._pdf_text()
        self.assertIn(
            "Alle bedragen in dit rapport zijn exclusief BTW.", summary_text
        )
        # subtotal 220.00, vat 46.20, total 266.20 across all four rows.
        self.assertIn("Excl. BTW: € 220,00", summary_text)
        self.assertIn("BTW: € 46,20", summary_text)
        self.assertIn("Incl. BTW: € 266,20", summary_text)
