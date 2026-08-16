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
stored total is still zero are touched. A row someone has already priced
by hand through the legacy surface is left exactly as it is: this command
repairs an absence, it does not arbitrate between two present numbers. Use
`--include-nonzero` to widen it to every approved-proposal row, which is
the escape hatch for a total that is wrong rather than missing; the table
then prints the old value beside the new one so a change is never silent.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from extra_work.final_amounts import quoted_totals, recompute_quoted_totals
from extra_work.models import ExtraWorkRequest, ProposalStatus


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

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        company_id = options["company"]
        include_nonzero = options["include_nonzero"]

        qs = (
            ExtraWorkRequest.objects.filter(
                deleted_at__isnull=True,
                proposals__status=ProposalStatus.CUSTOMER_APPROVED,
            )
            .distinct()
            .order_by("id")
        )
        if company_id is not None:
            qs = qs.filter(company_id=company_id)
        if not include_nonzero:
            qs = qs.filter(total_amount=Decimal("0.00"))

        rows = list(qs)
        self.stdout.write(
            f"\n{len(rows)} Extra Work row(s) with an approved proposal"
            + ("" if include_nonzero else " and a zero total")
            + (f" in company {company_id}" if company_id else "")
            + "."
        )
        if not rows:
            return

        self.stdout.write(
            f"  {'EW':>6}  {'old total':>12}  {'new total':>12}  title"
        )

        changed, unchanged, failed = 0, 0, []
        for ew in rows:
            old_total = ew.total_amount
            try:
                # `quoted_totals` COMPUTES and returns; only
                # `recompute_quoted_totals` below writes. That split is
                # what lets --dry-run print the real number it would
                # have written, from the one live formula rather than
                # from a second copy of it.
                _subtotal, _vat, new_total = quoted_totals(ew)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                failed.append((ew, exc))
                continue

            marker = " " if new_total == old_total else "*"
            self.stdout.write(
                f"  {ew.id:>6}  {old_total:>12}  {new_total:>12}{marker} "
                f"{ew.title[:48]}"
            )
            if new_total == old_total:
                unchanged += 1
                continue
            changed += 1
            if dry_run:
                continue
            try:
                with transaction.atomic():
                    recompute_quoted_totals(ew)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                failed.append((ew, exc))

        self.stdout.write("")
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run. {changed} row(s) WOULD change, "
                    f"{unchanged} already correct. Re-run without "
                    f"--dry-run to write them."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wrote {changed - len(failed)} row(s); "
                    f"{unchanged} were already correct."
                )
            )
        for ew, exc in failed:
            self.stdout.write(
                self.style.ERROR(f"  EW #{ew.id}: failed - {exc}")
            )
