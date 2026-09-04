"""
Sprint 191 §2.5 — the photo pool: visibility as its own axis.

Three additive columns and one backfill:

  * `TicketAttachment.visibility` — INTERNAL / CUSTOMER. The customer
    wall. Model default is INTERNAL (Addendum A §A.3.3: most
    restrictive), which is the DEFAULT FOR NEW STAFF UPLOADS, not a
    statement about the rows already stored.
  * `TicketAttachment.phase` — UNSPECIFIED / BEFORE / AFTER. A label
    with no behaviour attached, deliberately separate from visibility.
  * `Ticket.staff_uploads_customer_visible` — the per-work setting that
    makes staff uploads on THIS work customer-visible immediately.

The backfill is what makes this migration non-breaking: every
pre-existing attachment is written to the level it was ALREADY being
served at, so nothing that a customer could see yesterday disappears
and nothing they could not see appears. `is_hidden=True` rows (provider
management only) become INTERNAL; every other row was reaching the
customer already, so it becomes CUSTOMER.

Nothing here touches `is_hidden`, which is the only thing the
completion-evidence gates read.
"""
from django.db import migrations, models


def backfill_visibility(apps, schema_editor):
    TicketAttachment = apps.get_model("tickets", "TicketAttachment")
    TicketAttachment.objects.filter(is_hidden=False).update(visibility="CUSTOMER")
    TicketAttachment.objects.filter(is_hidden=True).update(visibility="INTERNAL")


def unbackfill_visibility(apps, schema_editor):
    """Reverse is a no-op: the column is dropped by the reversed
    AddField, so there is nothing to restore."""


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0026_sprint185_work_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='staff_uploads_customer_visible',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ticketattachment',
            name='phase',
            field=models.CharField(choices=[('UNSPECIFIED', 'Unspecified'), ('BEFORE', 'Before'), ('AFTER', 'After')], default='UNSPECIFIED', max_length=16),
        ),
        migrations.AddField(
            model_name='ticketattachment',
            name='visibility',
            field=models.CharField(choices=[('INTERNAL', 'Internal (provider side only)'), ('CUSTOMER', 'Customer visible')], default='INTERNAL', max_length=16),
        ),
        migrations.RunPython(backfill_visibility, unbackfill_visibility),
    ]
