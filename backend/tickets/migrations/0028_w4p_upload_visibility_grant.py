"""
W4-P — the two permission scopes for staff photo uploads.

Purely additive, no backfill, and deliberately so:

  * `UploadVisibilityGrant` — the new table. One row per explicit
    decision. `ticket IS NULL` is the STANDING scope (every ticket);
    `ticket` set is the PER-TICKET scope. Two PARTIAL unique constraints
    rather than one `unique_together`, because Postgres treats NULLs as
    distinct and a plain constraint would allow any number of standing
    rows for one person. An empty table on day one is the correct
    starting state: no grant means the pre-W4-P behaviour, unchanged.
  * `TicketAttachment.visibility_source` — which rung of the resolution
    ladder decided a row's `visibility` at upload. Blank on every
    pre-existing row, which reads "unrecorded" and NOT "default": we do
    not know what decided those, and inventing an answer for them would
    be worse than saying so.

Nothing here touches `visibility`, `is_hidden`, or any stored row's
value. What a customer could see the moment before this migration ran is
exactly what they can see the moment after.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0027_sprint191_attachment_visibility'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketattachment',
            name='visibility_source',
            field=models.CharField(blank=True, choices=[('', 'Unrecorded (pre-W4-P row)'), ('UPLOADER_CHOICE', 'Chosen by the uploader'), ('CUSTOMER_UPLOAD', "The customer's own upload"), ('TICKET_GRANT', 'Per-ticket permission'), ('STANDING_GRANT', 'Standing permission'), ('WORK_SETTING', 'Per-work setting'), ('DEFAULT_INTERNAL', 'Default (internal)'), ('MANUAL', 'Changed by hand afterwards')], default='', max_length=24),
        ),
        migrations.CreateModel(
            name='UploadVisibilityGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uploads_customer_visible', models.BooleanField(help_text="True = this person's uploads land customer-visible at this scope. False = they stay internal at this scope, overriding anything less specific. No default: the row exists only when somebody decided.")),
                ('reason', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('granted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='upload_visibility_grants_made', to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(blank=True, help_text='NULL = standing (every ticket). Set = this ticket only.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='upload_visibility_grants', to='tickets.ticket')),
                ('user', models.ForeignKey(help_text='The person whose uploads this decides.', on_delete=django.db.models.deletion.CASCADE, related_name='upload_visibility_grants', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['ticket', 'user'], name='tickets_upl_ticket__d46156_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('ticket__isnull', False)), fields=('user', 'ticket'), name='uniq_upload_visibility_grant_per_ticket'), models.UniqueConstraint(condition=models.Q(('ticket__isnull', True)), fields=('user',), name='uniq_upload_visibility_grant_standing')],
            },
        ),
    ]
