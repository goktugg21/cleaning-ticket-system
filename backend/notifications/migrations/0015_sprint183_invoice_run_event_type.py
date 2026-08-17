"""
Sprint 183 §3 — INVOICE_RUN_COMPLETED joins NotificationEventType.

Choices-only: Django keeps choices in migration state but Postgres has no
CHECK for them, so this alters no column and touches no data. The rows
Sprint 182's month-end job already wrote with the bare string keep
working and now render with a label instead of the raw value.

TWO models, not one — `NotificationPreference.event_type` composes the
email enum with the two in-app `NotificationType` values, so it moves
whenever the email enum does. Generated rather than hand-written for
exactly that reason: hand-typing a composed choices list is how one of
the two silently drifts.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0014_superadmincompanysubscription_email_enabled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationlog',
            name='event_type',
            field=models.CharField(choices=[('TICKET_CREATED', 'Ticket created'), ('TICKET_STATUS_CHANGED', 'Ticket status changed'), ('TICKET_ASSIGNED', 'Ticket assigned'), ('TICKET_UNASSIGNED', 'Ticket unassigned'), ('TICKET_SLOT_UNABLE', 'Staff slot unable to complete'), ('PASSWORD_RESET', 'Password reset'), ('INVITATION_SENT', 'Invitation sent'), ('INVOICE_RUN_COMPLETED', 'Invoice run completed')], max_length=64),
        ),
        migrations.AlterField(
            model_name='notificationpreference',
            name='event_type',
            field=models.CharField(choices=[('TICKET_CREATED', 'Ticket created'), ('TICKET_STATUS_CHANGED', 'Ticket status changed'), ('TICKET_ASSIGNED', 'Ticket assigned'), ('TICKET_UNASSIGNED', 'Ticket unassigned'), ('TICKET_SLOT_UNABLE', 'Staff slot unable to complete'), ('PASSWORD_RESET', 'Password reset'), ('INVITATION_SENT', 'Invitation sent'), ('INVOICE_RUN_COMPLETED', 'Invoice run completed'), ('TICKET_MESSAGE', 'Ticket message (in-app feed)'), ('EXTRA_WORK_MESSAGE', 'Extra work message (in-app feed)')], max_length=64),
        ),
    ]
