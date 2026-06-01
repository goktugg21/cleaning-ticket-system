"""Management command — manual / cron driver for planned-work
generation (Sprint 11B Batch 2). Mirrors `tasks.run_daily_planned_work`
for operators who prefer a one-shot CLI run."""
from django.core.management.base import BaseCommand

from planned_work.constants import DEFAULT_GENERATION_DAYS_AHEAD
from planned_work.generation import generate_occurrences
from planned_work.lifecycle import mark_missed_occurrences


class Command(BaseCommand):
    help = (
        "Generate planned-work occurrences + operational tickets within "
        "the horizon, then mark missed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=DEFAULT_GENERATION_DAYS_AHEAD,
            help="Look-ahead horizon in days (default: %(default)s).",
        )
        parser.add_argument(
            "--no-missed",
            action="store_true",
            help="Skip the missed-occurrence pass.",
        )

    def handle(self, *args, **options):
        result = generate_occurrences(days_ahead=options["days_ahead"])
        self.stdout.write(
            self.style.SUCCESS(
                "Generated %s occurrence(s), spawned %s ticket(s)."
                % (
                    result["occurrences_created"],
                    result["tickets_created"],
                )
            )
        )

        if not options["no_missed"]:
            missed = mark_missed_occurrences()
            self.stdout.write(
                self.style.SUCCESS("Marked %s occurrence(s) missed." % missed)
            )
