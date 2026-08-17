"""
Sprint 180 §1b — freeze the documents of invoices sent before the freeze
existed.

    python manage.py freeze_invoice_pdfs --dry-run
    python manage.py freeze_invoice_pdfs
    python manage.py freeze_invoice_pdfs --company osius-demo --limit 50

**Why this is a command and not a data migration.** Rendering every historic
invoice is real work — one PDF per row, each opening fonts and a logo — and a
migration is the worst possible place for it: it runs inside the deploy, it
runs on every environment whether or not anyone wanted it to, and if it fails
half way the deploy fails with it. The backfill is an operational decision, so
it is an operational command. The migration adds four nullable columns and
nothing else.

**Nothing is ever re-frozen.** The command only touches SENT invoices with no
`pdf_file`. A document that has already been frozen IS the artefact; replacing
its bytes is precisely what this sprint exists to prevent, so there is no
`--force`. If a frozen file is ever genuinely corrupt, that is a deliberate
one-off correction with a human deciding it — not a flag on a bulk command
that someone runs at 2am.

Invoices freeze lazily on first access too (`invoice_pdf_bytes`), so the
backfill is a way to do it all at once and on purpose rather than the only
way it can happen.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from companies.models import Company
from invoicing.invoice_pdf import freeze_invoice_pdf
from invoicing.models import Invoice


class Command(BaseCommand):
    help = (
        "Render and store the PDF of every SENT invoice that has none yet. "
        "Never re-freezes an invoice that already has one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help=(
                "Restrict to one provider company, by slug or numeric id. "
                "Omit to cover every company."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            help=(
                "Stop after N invoices. Use it to spread a large backfill "
                "over several runs rather than holding one long transaction."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be frozen and write nothing.",
        )

    def handle(self, *args, **options):
        # "No frozen file" is BOTH shapes: NULL (what the migration left on
        # every pre-existing row, and what a new row defaults to under
        # null=True) and "" (what a FileField holds when something clears it
        # without going through None). Matching only one of the two would
        # silently skip half the backlog.
        queryset = Invoice.objects.filter(
            status=Invoice.Status.SENT,
            deleted_at__isnull=True,
        ).filter(Q(pdf_file__isnull=True) | Q(pdf_file=""))

        company_ref = options.get("company")
        if company_ref:
            company = (
                Company.objects.filter(slug=company_ref).first()
                or (
                    Company.objects.filter(pk=int(company_ref)).first()
                    if company_ref.isdigit()
                    else None
                )
            )
            if company is None:
                raise CommandError(f"No company matches {company_ref!r}.")
            queryset = queryset.filter(company=company)

        queryset = queryset.select_related(
            "company", "customer", "building", "department", "work_type", "reverses"
        ).order_by("company_id", "year", "number", "id")

        limit = options.get("limit")
        pending = list(queryset[:limit] if limit else queryset)

        if not pending:
            self.stdout.write(
                self.style.SUCCESS(
                    "Nothing to do — every SENT invoice in scope already "
                    "carries a frozen PDF."
                )
            )
            return

        if options["dry_run"]:
            self.stdout.write(
                f"Would freeze {len(pending)} invoice(s):"
            )
            for invoice in pending:
                self.stdout.write(
                    f"  #{invoice.pk}  {invoice.number or '(no number)'}  "
                    f"{invoice.company.name}"
                )
            return

        frozen = 0
        failed: list[tuple[int, str]] = []
        for invoice in pending:
            # One transaction PER invoice, not one for the batch: a single
            # unrenderable row (a hard-deleted logo file, a corrupt logo
            # image) must not roll back the hundred that worked before it.
            try:
                with transaction.atomic():
                    locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
                    if locked.pdf_file:
                        continue
                    freeze_invoice_pdf(locked)
                frozen += 1
                self.stdout.write(
                    f"  frozen  #{invoice.pk}  {invoice.number or '(no number)'}  "
                    f"({locked.pdf_page_count} page(s))"
                )
            except Exception as exc:  # noqa: BLE001 — reported, never swallowed
                failed.append((invoice.pk, str(exc)))
                self.stderr.write(
                    self.style.ERROR(f"  FAILED  #{invoice.pk}: {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"Froze {frozen} invoice PDF(s).")
        )
        if failed:
            # A non-zero-ish signal in the text, because the operator reads
            # the last line and a silent partial success is a lie.
            self.stdout.write(
                self.style.WARNING(
                    f"{len(failed)} invoice(s) could not be frozen and were "
                    "left untouched; they will retry on the next run."
                )
            )
