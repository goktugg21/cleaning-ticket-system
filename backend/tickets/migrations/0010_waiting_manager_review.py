# Generated for Sprint 28 Batch 11 — STAFF completion routing.
#
# Adds the new `WAITING_MANAGER_REVIEW` enum value to TicketStatus and
# the `manager_review_at` timestamp column that gets stamped on entry
# to that status. The AlterField on `status` regenerates the choices
# list so the new value is accepted at the model layer; the AddField
# for `manager_review_at` is nullable so existing rows backfill to
# NULL without a data migration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0009_ticket_proposal_line"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticket",
            name="status",
            field=models.CharField(
                choices=[
                    ("OPEN", "Open"),
                    ("IN_PROGRESS", "In Progress"),
                    (
                        "WAITING_MANAGER_REVIEW",
                        "Waiting Manager Review",
                    ),
                    (
                        "WAITING_CUSTOMER_APPROVAL",
                        "Waiting Customer Approval",
                    ),
                    ("REJECTED", "Rejected"),
                    ("APPROVED", "Approved"),
                    ("CLOSED", "Closed"),
                    ("REOPENED_BY_ADMIN", "Reopened by Admin"),
                ],
                default="OPEN",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="manager_review_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
