"""Sprint W4-Q §1 — the three time-driven types reach the in-app feed.

Choices-only on a CharField: no column changes, no data moves. It exists
so `makemigrations --check` stays clean and so the admin renders the new
values with their labels instead of raw strings.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0017_sprint_w1b_sla_warning_events'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='event_type',
            field=models.CharField(choices=[('TICKET_MESSAGE', 'Ticket message'), ('EXTRA_WORK_REQUESTED', 'Extra work requested'), ('EXTRA_WORK_PROPOSAL_SENT', 'Extra work proposal sent'), ('EXTRA_WORK_DECISION', 'Extra work decision'), ('EXTRA_WORK_MESSAGE', 'Extra work message'), ('EXTRA_WORK_PUBLISHED', 'Extra work published'), ('SLA_APPROVAL_CUTOFF_DUE', 'Customer approval due before billing cutoff'), ('SLA_MANAGER_REVIEW_OVERDUE', 'Manager review overdue'), ('SLA_WORK_NOT_STARTED', 'Planned work has not started')], max_length=32),
        ),
    ]
