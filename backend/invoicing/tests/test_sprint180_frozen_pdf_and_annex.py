"""
Sprint 180 Batch 4 — the invoice becomes an artefact.

Three claims are pinned here, and they are different KINDS of claim:

1. **The freeze is real.** Not "a file exists" — that would pass while the
   endpoint still re-rendered. The digest recorded at send is compared
   against the bytes the endpoint serves AFTER the world behind the invoice
   has been changed underneath it. If anything re-rendered, the customer
   name would have moved and the SHA-256 would not match.
2. **The annex is the document the owner assembles by hand.** Grouped
   building -> department -> work type, one continuous numbering, a week
   column, and the page-1 summary line whose COUNT comes from the same
   `Annex` the pages are drawn from — so the two cannot drift.
3. **The privacy floor holds on EVERY page.** The existing PDF tests
   extract text with pypdf and assert customer-safe content. A multi-page
   invoice must be checked page by page: an annex that leaks an internal
   note or a cost price onto page 4 is the same failure as leaking it on
   page 1, and a test that only reads page 1 will not see it.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from io import BytesIO

from django.core.management import call_command
from pypdf import PdfReader
from rest_framework.test import APIClient

from customers.models import Customer
from extra_work.models import ExtraWorkRequest
from invoicing.annex import build_annex, summary_line
from invoicing.invoice_pdf import (
    freeze_invoice_pdf,
    invoice_pdf_bytes,
    render_invoice_pdf,
)
from invoicing.models import Invoice, InvoiceLine
from invoicing.services import generate_draft_invoices
from invoicing.state_machine import issue_invoice, reverse_invoice, send_invoice

from ._helpers import InvoicingFixture, dt

YEAR, MONTH = 2026, 5

# Sentinels the privacy tests grep for. Written onto the fields a leak would
# most plausibly come from — an EW's own description and its provider-only
# cost note — and asserted ABSENT from every page of the rendered document.
EW_DESCRIPTION_SENTINEL = "EW-DESCRIPTION-LEAK-XYZ"
INTERNAL_COST_SENTINEL = "INTERNAL-COST-LEAK-XYZ"


def _pages(data: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(BytesIO(data)).pages]


def _all_text(data: bytes) -> str:
    return "\n".join(_pages(data))


class _InvoiceBuilder(InvoicingFixture):
    """Builds real invoices through the real services, not by hand."""

    def _draft(self, n_lines=2, **ew_kwargs):
        for _ in range(n_lines):
            self.make_ew(closed_at=dt(2026, 5, 31), building=self.building, **ew_kwargs)
        return generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )[0]

    def _sent(self, n_lines=2, **ew_kwargs):
        return send_invoice(
            self.admin, issue_invoice(self.admin, self._draft(n_lines, **ew_kwargs))
        )

    def _api(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


# ---------------------------------------------------------------------------
# 1. The freeze
# ---------------------------------------------------------------------------


class FreezeAtSendTests(_InvoiceBuilder):
    def test_a_draft_is_not_frozen(self):
        """A draft is still changing and its preview is taken from it."""
        draft = self._draft()
        self.assertFalse(draft.pdf_file)
        self.assertIsNone(draft.pdf_frozen_at)
        self.assertEqual(draft.pdf_sha256, "")
        self.assertIsNone(draft.pdf_page_count)

    def test_an_issued_but_unsent_invoice_is_not_frozen_either(self):
        """The freeze is at SEND, not at issue — that decision is made."""
        issued = issue_invoice(self.admin, self._draft())
        self.assertFalse(issued.pdf_file)
        self.assertIsNone(issued.pdf_frozen_at)

    def test_send_freezes_the_document(self):
        sent = self._sent()
        self.assertTrue(sent.pdf_file)
        self.assertIsNotNone(sent.pdf_frozen_at)
        self.assertEqual(len(sent.pdf_sha256), 64)
        self.assertGreaterEqual(sent.pdf_page_count, 2)
        with sent.pdf_file.open("rb") as fh:
            stored = fh.read()
        self.assertTrue(stored.startswith(b"%PDF"))
        self.assertEqual(hashlib.sha256(stored).hexdigest(), sent.pdf_sha256)

    def test_the_frozen_page_count_is_the_real_page_count(self):
        """The count is taken from the renderer's own page list; this proves
        it agrees with what a reader counts."""
        sent = self._sent(n_lines=3)
        with sent.pdf_file.open("rb") as fh:
            stored = fh.read()
        self.assertEqual(sent.pdf_page_count, len(PdfReader(BytesIO(stored)).pages))

    def test_frozen_bytes_do_not_move_when_the_world_behind_them_changes(self):
        """THE test this sprint exists for.

        Send an invoice, then change the things the document renders — the
        customer's name, the building's name, an extra work's title — and
        confirm the endpoint still serves byte-for-byte what was committed.
        A re-render would move all three and the digest would not match.
        """
        sent = self._sent(n_lines=2)
        original_bytes = invoice_pdf_bytes(sent)
        original_digest = hashlib.sha256(original_bytes).hexdigest()
        self.assertEqual(original_digest, sent.pdf_sha256)
        self.assertIn(self.customer.name, _all_text(original_bytes))

        # Move the world.
        self.customer.name = "RENAMED CUSTOMER BV"
        self.customer.save(update_fields=["name"])
        self.building.name = "RENAMED BUILDING"
        self.building.save(update_fields=["name"])
        ExtraWorkRequest.objects.filter(
            invoice_lines__invoice=sent
        ).update(title="RENAMED WORK")

        served = invoice_pdf_bytes(Invoice.objects.get(pk=sent.pk))
        self.assertEqual(hashlib.sha256(served).hexdigest(), original_digest)
        self.assertEqual(served, original_bytes)
        text = _all_text(served)
        self.assertNotIn("RENAMED CUSTOMER BV", text)
        self.assertNotIn("RENAMED WORK", text)

        # And a FRESH render of the same row DOES move — which is what makes
        # the assertion above meaningful rather than a tautology about a
        # renderer that ignores its input.
        fresh = _all_text(render_invoice_pdf(Invoice.objects.get(pk=sent.pk)))
        self.assertIn("RENAMED CUSTOMER BV", fresh)

    def test_a_draft_pdf_still_re_renders_every_time(self):
        """The other half of the decision: a draft is NOT frozen, so editing
        it changes its preview."""
        draft = self._draft()
        before = invoice_pdf_bytes(draft)
        self.assertIn(self.customer.name, _all_text(before))
        self.customer.name = "DRAFT RENAME BV"
        self.customer.save(update_fields=["name"])
        after = invoice_pdf_bytes(Invoice.objects.get(pk=draft.pk))
        self.assertIn("DRAFT RENAME BV", _all_text(after))

    def test_freeze_is_idempotent(self):
        """Asking twice must give the same answer both times — the frozen
        document IS the artefact."""
        sent = self._sent()
        first_digest, first_at = sent.pdf_sha256, sent.pdf_frozen_at
        freeze_invoice_pdf(sent)
        sent.refresh_from_db()
        self.assertEqual(sent.pdf_sha256, first_digest)
        self.assertEqual(sent.pdf_frozen_at, first_at)

    def test_a_reversal_freezes_when_it_is_sent(self):
        sent = self._sent(n_lines=1)
        reversal = reverse_invoice(self.admin, sent)
        # Born ISSUED with its own number — not yet a sent document.
        self.assertFalse(reversal.pdf_file)
        reversal = send_invoice(self.admin, reversal)
        self.assertTrue(reversal.pdf_file)
        self.assertEqual(len(reversal.pdf_sha256), 64)


class LazyFreezeTests(_InvoiceBuilder):
    """§1(b) — an invoice sent before the field existed."""

    def _sent_without_a_frozen_file(self):
        sent = self._sent()
        sent.pdf_file.delete(save=False)
        Invoice.objects.filter(pk=sent.pk).update(
            pdf_file=None, pdf_sha256="", pdf_page_count=None, pdf_frozen_at=None
        )
        return Invoice.objects.get(pk=sent.pk)

    def test_first_provider_access_freezes_it(self):
        legacy = self._sent_without_a_frozen_file()
        self.assertFalse(legacy.pdf_file)
        resp = self._api(self.admin).get(f"/api/invoices/{legacy.pk}/pdf/")
        self.assertEqual(resp.status_code, 200)
        legacy.refresh_from_db()
        self.assertTrue(legacy.pdf_file)
        self.assertEqual(
            hashlib.sha256(resp.content).hexdigest(), legacy.pdf_sha256
        )

    def test_second_access_serves_the_same_bytes(self):
        legacy = self._sent_without_a_frozen_file()
        first = self._api(self.admin).get(f"/api/invoices/{legacy.pk}/pdf/").content
        # Change the world between the two reads: if the second access
        # re-rendered rather than reading the file frozen by the first, this
        # is where it would show.
        self.customer.name = "AFTER LAZY FREEZE BV"
        self.customer.save(update_fields=["name"])
        second = self._api(self.admin).get(f"/api/invoices/{legacy.pk}/pdf/").content
        self.assertEqual(first, second)
        self.assertNotIn("AFTER LAZY FREEZE BV", _all_text(second))

    def test_the_backfill_command_freezes_what_is_left(self):
        legacy = self._sent_without_a_frozen_file()
        call_command("freeze_invoice_pdfs", verbosity=0)
        legacy.refresh_from_db()
        self.assertTrue(legacy.pdf_file)
        self.assertEqual(len(legacy.pdf_sha256), 64)

    def test_the_backfill_command_never_refreezes(self):
        sent = self._sent()
        before = sent.pdf_sha256, sent.pdf_frozen_at
        call_command("freeze_invoice_pdfs", verbosity=0)
        sent.refresh_from_db()
        self.assertEqual((sent.pdf_sha256, sent.pdf_frozen_at), before)

    def test_the_backfill_command_dry_run_writes_nothing(self):
        legacy = self._sent_without_a_frozen_file()
        call_command("freeze_invoice_pdfs", "--dry-run", verbosity=0)
        legacy.refresh_from_db()
        self.assertFalse(legacy.pdf_file)

    def test_the_backfill_command_ignores_drafts(self):
        draft = self._draft()
        call_command("freeze_invoice_pdfs", verbosity=0)
        draft.refresh_from_db()
        self.assertFalse(draft.pdf_file)


# ---------------------------------------------------------------------------
# 2. The annex
# ---------------------------------------------------------------------------


class AnnexGroupingTests(_InvoiceBuilder):
    """The grouping as DATA — no PDF. This is the half where bugs live."""

    def _tagged_draft(self):
        # Two buildings, two departments, two work types, so every level of
        # the building -> department -> work type key is exercised.
        self.make_ew(
            closed_at=dt(2026, 5, 4), building=self.building,
            department=self.dept_a, work_type=self.wt_a,
        )
        self.make_ew(
            closed_at=dt(2026, 5, 11), building=self.building,
            department=self.dept_a, work_type=self.wt_b,
        )
        self.make_ew(
            closed_at=dt(2026, 5, 18), building=self.building2,
            department=self.dept_b, work_type=self.wt_a,
        )
        self.make_ew(closed_at=dt(2026, 5, 25), building=self.building2)
        return generate_draft_invoices(
            self.admin,
            self.company.id,
            self.customer.id,
            YEAR,
            MONTH,
            granularity=Customer.InvoiceGranularity.CUSTOMER,
        )[0]

    def test_groups_by_building_then_department_then_work_type(self):
        annex = build_annex(self._tagged_draft())
        self.assertEqual(
            [(g.building, g.department, g.work_type) for g in annex.groups],
            [
                ("A-B1", "Dept A", "WT A"),
                ("A-B1", "Dept A", "WT B"),
                ("A-B2", "Dept B", "WT A"),
                # Untagged sorts LAST within its building, not first.
                ("A-B2", "", ""),
            ],
        )

    def test_numbering_is_continuous_across_groups(self):
        annex = build_annex(self._tagged_draft())
        indexes = [row.index for group in annex.groups for row in group.rows]
        self.assertEqual(indexes, [1, 2, 3, 4])

    def test_a_row_carries_the_week_and_the_completion_date(self):
        annex = build_annex(self._tagged_draft())
        first = annex.groups[0].rows[0]
        # 2026-05-04 is a Monday in ISO week 19.
        self.assertEqual(first.week, "19")
        self.assertEqual(first.completed, "04-05-2026")

    def test_amounts_come_from_the_invoice_line_not_the_extra_work(self):
        """"Read invoice.lines; do not re-derive amounts from the extra
        works. The invoice is the source of truth for its own money."""
        invoice = self._tagged_draft()
        line = invoice.lines.order_by("ordering").first()
        # Marked by DESCRIPTION, not by position: the annex re-orders lines
        # into building/department/work-type groups, so "the first line" and
        # "the first row" are not the same row.
        InvoiceLine.objects.filter(pk=line.pk).update(
            description="MARKED LINE", line_subtotal=Decimal("999.99")
        )
        ExtraWorkRequest.objects.filter(pk=line.extra_work_id).update(
            subtotal_amount=Decimal("1.00"),
            final_subtotal_amount=Decimal("2.00"),
        )
        annex = build_annex(Invoice.objects.get(pk=invoice.pk))
        rows = {r.title: r for g in annex.groups for r in g.rows}
        self.assertIn("MARKED LINE", rows)
        self.assertEqual(rows["MARKED LINE"].subtotal, Decimal("999.99"))

    def test_a_heading_prints_only_the_parts_that_exist(self):
        annex = build_annex(self._tagged_draft())
        headings = [g.heading() for g in annex.groups]
        self.assertEqual(headings[0], "A-B1 - Dept A - WT A")
        self.assertEqual(headings[-1], "A-B2")

    def test_the_annex_total_plus_the_fee_is_the_invoice_subtotal(self):
        invoice = self._tagged_draft()
        annex = build_annex(invoice)
        fee = invoice.optional_fee_amount or Decimal("0.00")
        self.assertEqual(annex.subtotal + fee, invoice.subtotal_amount)

    def test_a_hand_added_line_is_listed_under_the_invoice_building(self):
        """A line with no extra work is money on this invoice that is not a
        claimed extra work — it is still listed, not silently dropped."""
        invoice = self._draft(n_lines=1)
        InvoiceLine.objects.create(
            invoice=invoice,
            ordering=99,
            description="Handmatige regel",
            extra_work=None,
            line_subtotal=Decimal("10.00"),
            line_vat=Decimal("2.10"),
            line_total=Decimal("12.10"),
        )
        annex = build_annex(Invoice.objects.get(pk=invoice.pk))
        titles = [r.title for g in annex.groups for r in g.rows]
        self.assertIn("Handmatige regel", titles)


class AnnexSummaryLineTests(_InvoiceBuilder):
    def test_singular_and_plural(self):
        self.assertEqual(
            summary_line(build_annex(self._draft(n_lines=1))),
            "1 meerwerk - Zie bijlage voor specificatie",
        )
        self.assertEqual(
            summary_line(build_annex(self._draft(n_lines=3))).split(" ")[0],
            "3",
        )

    def test_page_one_count_equals_the_annex_row_count(self):
        """The count on page 1 and the rows overleaf come from ONE `Annex`,
        so they cannot disagree — pinned rather than trusted."""
        invoice = self._draft(n_lines=4)
        annex = build_annex(invoice)
        self.assertIn(f"{annex.row_count} meerwerken", summary_line(annex))
        page1 = _pages(render_invoice_pdf(invoice))[0]
        self.assertIn(f"{annex.row_count} meerwerken", page1)

    def test_page_one_states_subtotal_vat_and_total(self):
        invoice = self._draft(n_lines=2)
        page1 = _pages(render_invoice_pdf(invoice))[0]
        # "157,40 + 21% = 190,45" — the shape from the owner's own invoice.
        self.assertIn("21%", page1)
        self.assertIn("200,00", page1)  # 2 x 100.00 subtotal
        self.assertIn("242,00", page1)  # 2 x 121.00 total

    def test_mixed_vat_rates_state_the_amount_instead_of_a_percentage(self):
        """A single "21%" would misdescribe a mixed-rate invoice."""
        invoice = self._draft(n_lines=2)
        first = invoice.lines.order_by("ordering").first()
        InvoiceLine.objects.filter(pk=first.pk).update(vat_pct=Decimal("9.00"))
        page1 = _pages(render_invoice_pdf(Invoice.objects.get(pk=invoice.pk)))[0]
        self.assertNotIn("+ 21% =", page1)
        self.assertIn("BTW =", page1)


class AnnexRenderingTests(_InvoiceBuilder):
    def test_every_annex_page_repeats_the_header_and_the_columns(self):
        """"A page that arrives on its own must still say what it is." """
        invoice = self._draft(n_lines=40)
        pages = _pages(render_invoice_pdf(invoice))
        self.assertGreater(len(pages), 2, "40 lines should overflow one page")
        for index, text in enumerate(pages[1:], start=2):
            with self.subTest(page=index):
                self.assertIn(self.company.name, text)
                self.assertIn("Titel", text)
                self.assertIn("Week", text)
                self.assertIn("Excl. BTW", text)

    def test_a_long_invoice_runs_to_many_pages(self):
        """The owner's point: an invoice can run to eight pages."""
        invoice = self._draft(n_lines=120)
        self.assertGreaterEqual(len(_pages(render_invoice_pdf(invoice))), 4)

    def test_an_invoice_with_no_lines_still_renders_an_annex_page(self):
        invoice = Invoice.objects.create(
            company=self.company,
            customer=self.customer,
            status=Invoice.Status.DRAFT,
            created_by=self.admin,
        )
        pages = _pages(render_invoice_pdf(invoice))
        self.assertEqual(len(pages), 2)
        self.assertIn("Geen meerwerk", pages[0])
        self.assertIn("geen meerwerkregels", pages[1].lower())


class ReversalAnnexTests(_InvoiceBuilder):
    """§1(a) — a credit note has no extra works to list."""

    def _reversal(self):
        sent = self._sent(n_lines=2)
        return sent, reverse_invoice(self.admin, sent)

    def test_the_annex_is_empty_and_carries_the_original_number(self):
        sent, reversal = self._reversal()
        annex = build_annex(reversal)
        self.assertEqual(annex.groups, ())
        self.assertEqual(annex.reverses_number, sent.number)

    def test_the_summary_line_references_the_original(self):
        sent, reversal = self._reversal()
        self.assertEqual(
            summary_line(build_annex(reversal)),
            f"Creditering van factuur {sent.number} - Zie bijlage",
        )

    def test_the_rendered_credit_note_says_what_it_credits(self):
        sent, reversal = self._reversal()
        pages = _pages(render_invoice_pdf(reversal))
        self.assertIn("Creditnota", pages[0])
        self.assertIn(sent.number, pages[0])
        self.assertIn(sent.number, pages[1])
        # It does NOT invent line data that is not there.
        self.assertNotIn("Subtotaal specificatie", pages[1])


# ---------------------------------------------------------------------------
# 3. The privacy floor, page by page
# ---------------------------------------------------------------------------


class AnnexPrivacyTests(_InvoiceBuilder):
    """A leak on page 4 is the same failure as a leak on page 1."""

    def _invoice_with_sentinels(self, n_lines=45):
        invoice = self._draft(n_lines=n_lines)
        # Write the sentinels onto the EW fields a careless annex would read.
        ExtraWorkRequest.objects.filter(invoice_lines__invoice=invoice).update(
            description=EW_DESCRIPTION_SENTINEL,
            internal_cost_note=INTERNAL_COST_SENTINEL,
        )
        return Invoice.objects.get(pk=invoice.pk)

    def test_no_page_carries_an_internal_extra_work_field(self):
        data = render_invoice_pdf(self._invoice_with_sentinels())
        pages = _pages(data)
        # Load-bearing: a document that happened to be two pages long would
        # make "checked every page" a much weaker claim than it sounds.
        self.assertGreater(len(pages), 2, "fixture must span several pages")
        for index, text in enumerate(pages, start=1):
            with self.subTest(page=index):
                self.assertNotIn(EW_DESCRIPTION_SENTINEL, text)
                self.assertNotIn(INTERNAL_COST_SENTINEL, text)
        # Also absent from the RAW bytes — extraction can miss text that a
        # copy-paste would find.
        self.assertNotIn(EW_DESCRIPTION_SENTINEL.encode(), data)
        self.assertNotIn(INTERNAL_COST_SENTINEL.encode(), data)

    def test_the_frozen_document_a_customer_downloads_is_equally_clean(self):
        invoice = self._invoice_with_sentinels(n_lines=45)
        sent = send_invoice(self.admin, issue_invoice(self.admin, invoice))
        data = invoice_pdf_bytes(sent)
        for index, text in enumerate(_pages(data), start=1):
            with self.subTest(page=index):
                self.assertNotIn(EW_DESCRIPTION_SENTINEL, text)
                self.assertNotIn(INTERNAL_COST_SENTINEL, text)

    def test_the_annex_does_carry_the_customer_facing_facts(self):
        """The other side of the same claim — a redaction that removed
        everything would also pass the test above."""
        invoice = self._draft(n_lines=2)
        text = "\n".join(_pages(render_invoice_pdf(invoice))[1:])
        self.assertIn("Work performed", text)  # the line description
        self.assertIn(self.building.name, text)


# ---------------------------------------------------------------------------
# 4. The exposed fields, on a rendered endpoint
# ---------------------------------------------------------------------------


class ExposedFieldTests(_InvoiceBuilder):
    """Sprint 173's lesson: a missing `fields` entry took a whole page down
    and a filter test never catches it, because a filter test issues a query
    but never serialises a row."""

    def test_provider_detail_carries_the_freeze_fields(self):
        sent = self._sent()
        resp = self._api(self.admin).get(f"/api/invoices/{sent.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pdf_frozen_at", resp.data)
        self.assertIn("pdf_page_count", resp.data)
        self.assertIsNotNone(resp.data["pdf_frozen_at"])
        self.assertEqual(resp.data["pdf_page_count"], sent.pdf_page_count)

    def test_provider_list_carries_them_too(self):
        self._sent()
        resp = self._api(self.admin).get("/api/invoices/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertTrue(rows)
        self.assertIn("pdf_frozen_at", rows[0])
        self.assertIn("pdf_page_count", rows[0])

    def test_a_draft_reports_them_as_null(self):
        draft = self._draft()
        resp = self._api(self.admin).get(f"/api/invoices/{draft.pk}/")
        self.assertIsNone(resp.data["pdf_frozen_at"])
        self.assertIsNone(resp.data["pdf_page_count"])

    def test_the_customer_shape_does_not_leak_the_digest_or_the_path(self):
        """The customer serializer is redacted and stays that way — the
        integrity digest and the on-disk path are provider-internal."""
        sent = self._sent()
        resp = self._api(self.admin).get(f"/api/invoices/{sent.pk}/")
        self.assertNotIn("pdf_sha256", resp.data)
        self.assertNotIn("pdf_file", resp.data)


class MediaIsolationSelfTest(_InvoiceBuilder):
    """The isolation itself, asserted rather than assumed.

    Sending an invoice writes a real file, and a `TestCase` rolls rows back
    but never files. Without this the suite would deposit PDFs into the
    developer's own `backend/media/` and leave them there.
    """

    def test_files_land_in_the_isolated_media_root(self):
        sent = self._sent()
        path = sent.pdf_file.path
        self.assertTrue(path.startswith(self._media_dir), path)
        # The real MEDIA_ROOT is `<BASE_DIR>/media`; nothing may land there.
        self.assertNotIn("/app/media/", path)
