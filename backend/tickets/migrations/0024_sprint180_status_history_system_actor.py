"""
Sprint 180 §1 — allow a SYSTEM-authored TicketStatusHistory row.

Additive and reversible: `changed_by` goes from NOT NULL to NULL-able.
No existing row changes, no column is dropped, and `on_delete` stays
PROTECT (a real actor still cannot be deleted out from under their own
history). NULL is written only by `tickets/auto_close.py`, which drives
the customer-approval `APPROVED -> CLOSED` transition with no human
actor.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0023_sprint143_ticket_type_other"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketstatushistory",
            name="changed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ticket_status_changes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
