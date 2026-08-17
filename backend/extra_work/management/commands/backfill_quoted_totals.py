"""Sprint 187 §1 — write the quote cache for Extra Work priced through a
Proposal before the freeze existed.

`ExtraWorkRequest.subtotal_amount` / `vat_amount` / `total_amount` are the
quote cache every list, dashboard widget, report KPI, CSV export and
detail header reads. Until this sprint the only thing that wrote them was
`recompute_totals()`, driven exclusively from the legacy
`/extra-work/<id>/pricing-items/` views. The Proposal route never touched
them, so an Extra Work quoted at EUR 484.00 through a Proposal — approved
by the customer, ticket spawned, work under way — read EUR 0,00
everywhere. `proposal_state_machine._advance_parent_on_customer_decision`
now freezes them at approval, which fixes every future row and none of
the rows already sitting on crmtest.

This command is those rows.

A management command and NOT a data migration, by instruction and on
merit: the recompute reads the approved proposal's lines, so it is a
business recomputation rather than a schema consequence, and it belongs
behind a human who has read a `--dry-run` first.

SAFE TO RE-RUN. `recompute_quoted_totals` is a pure recomputation from
the approved proposal's lines — running it twice writes the same numbers.

DELIBERATELY NARROW. Only rows that have an approved proposal AND whose
stored quote cache is still zero are touched. A row someone has already priced
by hand through the legacy surface is left exactly as it is: this command
repairs an absence, it does not arbitrate between two present numbers. Use
`--include-nonzero` to widen it to every approved-proposal row, which is
the escape hatch for a total that is wrong rather than missing; the table
then prints the old value beside the new one so a change is never silent.

## Sprint 187C — what an invoice does to this

An Extra Work that already sits on an invoice is NOT this command's to
re-price unasked, and the repo already says so in a neighbouring case:
`extra_work/label_validation.py` freezes an EW's department / work type
once it is carried by an ISSUED invoice, and prescribes credit -> relabel
-> re-invoice instead of an in-place edit. Money deserves at least that.

The invoice's OWN amounts are never at risk — they are snapshotted into
`InvoiceLine` when the draft is built and re-derive only from those lines,
so nothing here can alter what a customer was billed. The risk is quieter:
the Extra Work row would start displaying a number that disagrees with the
invoice that billed it, with no record of who changed it.

So rows are classified before anything is written:

  * on an ISSUED or SENT invoice -> SETTLED. Skipped, listed, and only
    reachable with the explicit `--include-invoiced`.
  * on a DRAFT invoice only -> DRAFT. Repaired (a draft IS the correction
    window) but flagged, because that draft was built from the old number
    and should be regenerated afterwards.
  * on no invoice -> repaired silently.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from extra_work.final_amounts import quoted_totals, recompute_quoted_totals
from extra_work.models import ExtraWorkRequest, ProposalStatus
from invoicing.models import Invoice


class Command(BaseCommand):
    help = (
        "Recompute the quote cache (subtotal / vat / total) for Extra "
        "Work rows priced through an approved Proposal. Reports what it "
        "would change with --dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Print the table and write nothing. The same table is "
                "printed either way."
            ),
        )
        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help="Limit to one provider company id.",
        )
        parser.add_argument(
            "--include-nonzero",
            action="store_true",
            help=(
                "Also recompute rows whose total is already non-zero. "
                "Off by default — a stored total that is present was put "
                "there by something and is not this command's to "
                "overwrite unasked."
            ),
        )
        parser.add_argument(
            "--include-invoiced",
            action="store_true",
            help=(
                "Also repair rows already carried by an ISSUED or SENT "
                "invoice. Off by default: the invoice's own amounts are "
                "immutable, so repairing the Extra Work makes the two "
                "disagree unless you are correcting the invoice too."
            ),
        )

    @staticmethod
    def _invoice_claim(ew) -> tuple[str, str]:
        """How firmly an invoice has hold of `ew`.

        Returns `("SETTLED", "<statuses>")` when any invoice carrying it
        is ISSUED or SENT — past the point where an in-place correction
        is honest — `("DRAFT", "draft")` when only drafts carry it, and
        `("", "")` when nothing does.
        """
        statuses = {
            line.invoice.status
            for line in ew.invoice_lines.all()
            if line.invoice_id is not None
        }
        settled = sorted(
            statuses & {Invoice.Status.ISSUED, Invoice.Status.SENT}
        )
        if settled:
            return "SETTLED", "/".join(settled)
        if Invoice.Status.DRAFT in statuses:
            return "DRAFT", "draft"
        return "", ""

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        company_id = options["company"]
        include_nonzero = options["include_nonzero"]
        include_invoiced = options["include_invoiced"]

        qs = (
            ExtraWorkRequest.objects.filter(
                deleted_at__isnull=True,
                proposals__status=ProposalStatus.CUSTOMER_APPROVED,
            )
            .distinct()
            .order_by("id")
            # One query for the invoice claim of every row, instead of
            # two per row inside the loop below.
            .prefetch_related("invoice_lines__invoice")
        )
        if company_id is not None:
            qs = qs.filter(company_id=company_id)
        if not include_nonzero:
            qs = qs.filter(total_amount=Decimal("0.00"))

        rows = list(qs)
        self.stdout.write(
            f"\n{len(rows)} Extra Work row(s) with an approved proposal"
            + ("" if include_nonzero else " and a zero total")
            + (f" in company {company_id}" if company_id is not None else "")
            + "."
        )
        if not rows:
            return

        self.stdout.write(
            f"  {'EW':>6}  {'old total':>12}  {'new total':>12}  title"
        )

        would_change, wrote, unchanged = 0, 0, 0
        skipped_invoiced, refused_zero, failed = [], [], []

        for ew in rows:
            claim, claim_label = self._invoice_claim(ew)
            if claim == "SETTLED" and not include_invoiced:
                skipped_invoiced.append((ew, claim_label))
                continue

            # All THREE columns, not just the total. A row whose total
            # happens to match while its subtotal/VAT split is wrong is
            # still a broken row, and comparing only the total would
            # report it as "already correct" and never repair it.
            old = (ew.subtotal_amount, ew.vat_amount, ew.total_amount)
            try:
                # `quoted_totals` COMPUTES and returns; only
                # `recompute_quoted_totals` below writes. That split is
                # what lets --dry-run print the real number it would
                # have written, from the one live formula rather than
                # from a second copy of it.
                new = quoted_totals(ew)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                failed.append((ew, exc))
                continue

            differs = new != old
            flag = ""
            if claim == "DRAFT":
                flag = "  [on a draft invoice - regenerate it]"
            elif claim == "SETTLED":
                flag = f"  [on a {claim_label} invoice]"
            self.stdout.write(
                f"  {ew.id:>6}  {old[2]:>12}  {new[2]:>12}"
                f"{'*' if differs else ' '} {ew.title[:48]}{flag}"
            )
            if not differs:
                unchanged += 1
                continue

            # Never blank out a total that is present. Reached only under
            # --include-nonzero, where an EW whose latest approved
            # proposal has no spawn-approved lines resolves to 0.00 — a
            # recomputation that would ERASE a real number rather than
            # supply a missing one, which is the opposite of this
            # command's job.
            if new[2] == Decimal("0.00") and old[2] != Decimal("0.00"):
                refused_zero.append(ew)
                continue

            would_change += 1
            if dry_run:
                continue
            try:
                with transaction.atomic():
                    recompute_quoted_totals(ew)
                wrote += 1
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                failed.append((ew, exc))

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run. {would_change} row(s) WOULD change, "
                    f"{unchanged} already correct. Re-run without "
                    f"--dry-run to write them."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {wrote} row(s); "
                    f"{unchanged} were already correct."
                )
            )

        if skipped_invoiced:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{len(skipped_invoiced)} row(s) SKIPPED — already "
                    f"carried by an issued or sent invoice. Their invoice "
                    f"amounts are immutable, so repairing the Extra Work "
                    f"alone would make the two disagree. Correct the "
                    f"invoice by reversal, or pass --include-invoiced if "
                    f"you know what you are doing."
                )
            )
            for ew, label in skipped_invoiced:
                self.stdout.write(f"  EW #{ew.id}: on a {label} invoice")

        if refused_zero:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{len(refused_zero)} row(s) REFUSED — recomputing "
                    f"would replace a real total with 0.00. Nothing was "
                    f"written; check the approved proposal's lines."
                )
            )
            for ew in refused_zero:
                self.stdout.write(
                    f"  EW #{ew.id}: kept {ew.total_amount}"
                )

        for ew, exc in failed:
            self.stdout.write(
                self.style.ERROR(f"  EW #{ew.id}: failed - {exc}")
            )
