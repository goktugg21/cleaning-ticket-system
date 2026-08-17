"""
Sprint 164 §8 — run the contract invoice generator deliberately.

A COMMAND rather than a Celery beat entry, on purpose. This is the
first thing in the system that creates money documents without a person
pressing a button, and it should be run and reviewed by hand before it
runs by itself.

Wiring it to beat later is small: add an entry to `CELERY_BEAT_SCHEDULE`
in `config/settings.py` pointing at a task that calls
`contracts.invoice_generation.generate_invoices()`, the same callable
this command uses. What that change needs on top of the code is a
decision nobody has made yet — how often, at what hour, and whether a
run that spans midnight may bill a period a day early — which is
exactly why it is not being made in passing here.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from companies.models import Company
from contracts.invoice_generation import generate_invoices


class Command(BaseCommand):
    help = (
        "Create DRAFT invoices for every contract period whose invoice "
        "date has arrived and which is not already invoiced."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help="Limit to one provider company id.",
        )
        parser.add_argument(
            "--on",
            type=str,
            default=None,
            help=(
                "Run as if today were this date (YYYY-MM-DD). For catching "
                "up deliberately, and for reproducing a run."
            ),
        )
        parser.add_argument(
            "--actor",
            type=str,
            required=True,
            help=(
                "Email of the user the invoices are created BY. Required: "
                "Invoice.created_by is NOT NULL, and a scheduled run has "
                "to answer that question in configuration rather than "
                "from a request."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what WOULD be created and roll it back.",
        )

    def handle(self, *args, **options):
        from django.db import transaction

        company = None
        if options["company"] is not None:
            company = Company.objects.filter(pk=options["company"]).first()
            if company is None:
                raise CommandError(f"No company with id {options['company']}")

        from accounts.models import User

        actor = User.objects.filter(email=options["actor"]).first()
        if actor is None:
            raise CommandError(f"No user with email {options['actor']!r}")

        on = None
        if options["on"]:
            try:
                on = date.fromisoformat(options["on"])
            except ValueError as exc:
                raise CommandError(f"--on must be YYYY-MM-DD: {exc}")

        def run():
            result = generate_invoices(actor=actor, company=company, on=on)
            self.stdout.write(
                f"created={result.created_count} "
                f"already_invoiced={result.skipped_existing} "
                f"no_revision={result.skipped_no_revision}"
            )
            for invoice in result.created:
                self.stdout.write(
                    f"  DRAFT invoice #{invoice.pk} "
                    f"customer={invoice.customer_id} "
                    f"total={invoice.total_amount}"
                )
            return result

        if options["dry_run"]:
            # A real run inside a rolled-back transaction: the numbers
            # reported are what would actually happen, not a second
            # code path guessing at it.
            try:
                with transaction.atomic():
                    run()
                    raise _Rollback()
            except _Rollback:
                self.stdout.write(self.style.WARNING("dry run - rolled back"))
        else:
            run()


class _Rollback(Exception):
    """Internal: unwinds the dry-run transaction."""
