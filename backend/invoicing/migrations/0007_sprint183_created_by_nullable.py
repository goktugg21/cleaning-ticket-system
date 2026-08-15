"""
Sprint 183 §3 — an invoice may be created by the system.

Additive and reversible in shape: `Invoice.created_by` goes from NOT NULL
to NULL-able, meaning "no person created this; the month-end run did".
No existing row changes and `on_delete` stays PROTECT, so a real actor
still cannot be deleted out from under invoices they created.

NOTE ON REVERSING: `AlterField` back to NOT NULL will fail if any
system-created invoice exists by then, which is correct — the database
refusing is better than silently inventing an author for a row that has
none. Reversing this migration means first deciding who those invoices
should be attributed to.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("invoicing", "0006_sprint180_frozen_invoice_pdf"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_invoices",
                to=settings.AUTH_USER_MODEL,
                help_text=(
                    "Who created this invoice. NULL = the system (the "
                    "month-end run); every read surface renders that as "
                    "'System'."
                ),
            ),
        ),
    ]
