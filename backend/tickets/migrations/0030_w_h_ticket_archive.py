"""W-H §1 — the ticket archive.

Three ADDITIVE nullable columns and no data migration: every existing
ticket has `archived_at IS NULL`, which is exactly "not archived", so
there is no historical state to invent. The list excludes archived rows
by default from the moment this lands, and until somebody archives
something that exclusion removes nothing.

`archived_by` is SET_NULL rather than PROTECT, matching `deleted_by`
directly above it in the model: deactivating a leaver must not be
blocked by work they once filed away, and the AuditLog row carries who
did it independently of this FK.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0029_w10_acknowledged_and_on_hold'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='archive_note',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='ticket',
            name='archived_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='ticket',
            name='archived_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='archived_tickets', to=settings.AUTH_USER_MODEL),
        ),
    ]
