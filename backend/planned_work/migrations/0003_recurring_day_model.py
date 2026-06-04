# Recurring day-model: weekday sets + per-day windows + per-occurrence
# billing. Adds RecurringJobWindow, RecurringJob.weekdays, and the
# PlannedOccurrence.source_window anchor, then backfills legacy data so the
# generator produces byte-identical output for any unchanged job.

import django.db.models.deletion
from django.db import migrations, models


def backfill_windows_and_source(apps, schema_editor):
    """Make every pre-existing RecurringJob day-model-shaped and re-anchor
    its occurrences, so generation is byte-identical after this migration:

    1. Create exactly ONE default window per job, from its legacy
       `preferred_start_time` / `time_window_label` (pricing left null so
       the occurrence keeps falling back to the job's pricing).
    2. Seed the job's weekday set to {start_date's ISO weekday} for
       WEEKLY / BIWEEKLY (the legacy single-weekday series); MONTHLY keeps
       an empty set (it anchors on the day-of-month).
    3. Point every existing occurrence's `source_window` at its job's
       default window, so the not-null tightening + the new
       (job, date, window) unique anchor hold on legacy rows.

    Idempotent enough for a one-shot data migration; uses the historical
    models via apps.get_model (which do NOT fire app signals, so no audit
    rows are emitted for these system writes).
    """
    RecurringJob = apps.get_model("planned_work", "RecurringJob")
    RecurringJobWindow = apps.get_model("planned_work", "RecurringJobWindow")
    PlannedOccurrence = apps.get_model("planned_work", "PlannedOccurrence")

    default_window_by_job = {}
    for job in RecurringJob.objects.all().iterator():
        window = RecurringJobWindow.objects.create(
            recurring_job=job,
            label=job.time_window_label or "",
            start_time=job.preferred_start_time,
            ordering=0,
            is_active=True,
            pricing_mode=None,
            fixed_price=None,
            vat_pct=None,
        )
        default_window_by_job[job.id] = window

        if job.frequency in ("WEEKLY", "BIWEEKLY"):
            job.weekdays = str(job.start_date.isoweekday())
        else:
            job.weekdays = ""
        job.save(update_fields=["weekdays"])

    for occ in PlannedOccurrence.objects.all().iterator():
        window = default_window_by_job.get(occ.recurring_job_id)
        if window is None:
            # Defensive: an occurrence whose job we did not just window
            # (should be impossible — one window per job above). Create the
            # default window now so no occurrence is left unanchored.
            job = RecurringJob.objects.get(pk=occ.recurring_job_id)
            window = RecurringJobWindow.objects.create(
                recurring_job=job,
                label=job.time_window_label or "",
                start_time=job.preferred_start_time,
                ordering=0,
                is_active=True,
            )
            default_window_by_job[job.id] = window
        occ.source_window = window
        occ.save(update_fields=["source_window"])


class Migration(migrations.Migration):

    dependencies = [
        ("planned_work", "0002_plannedoccurrence_fixed_price_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecurringJobWindow",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("label", models.CharField(blank=True, default="", max_length=64)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("ordering", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "pricing_mode",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("CONTRACT_INCLUDED", "Contract included"),
                            ("FIXED", "Fixed price"),
                            (
                                "HOURLY",
                                "Hourly (reserved — no actual-hours plumbing in 11B)",
                            ),
                        ],
                        max_length=24,
                        null=True,
                    ),
                ),
                (
                    "fixed_price",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=10, null=True
                    ),
                ),
                (
                    "vat_pct",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=5, null=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "recurring_job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="windows",
                        to="planned_work.recurringjob",
                    ),
                ),
            ],
            options={
                "ordering": ["ordering", "id"],
            },
        ),
        migrations.AddField(
            model_name="recurringjob",
            name="weekdays",
            field=models.CharField(blank=True, default="", max_length=27),
        ),
        # source_window starts nullable so the backfill can run; tightened
        # to non-null below once every occurrence has been anchored.
        migrations.AddField(
            model_name="plannedoccurrence",
            name="source_window",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="occurrences",
                to="planned_work.recurringjobwindow",
            ),
        ),
        migrations.RunPython(
            backfill_windows_and_source, migrations.RunPython.noop
        ),
        migrations.AlterField(
            model_name="plannedoccurrence",
            name="source_window",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="occurrences",
                to="planned_work.recurringjobwindow",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="plannedoccurrence",
            unique_together={("recurring_job", "planned_date", "source_window")},
        ),
    ]
