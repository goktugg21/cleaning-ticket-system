"""
Ticket save signal handlers that drive the SLA engine.

Wiring is set up in apps.SlaConfig.ready(). Persistence inside the handler
uses Ticket.objects.filter(pk=).update(...) to bypass signal recursion;
since update() does not refresh the in-memory instance, the engine mutates
attributes on `instance` first so callers reading the instance after save()
see consistent SLA fields.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from tickets.models import Ticket

from . import services


_OLD_STATUS_ATTR = "_sla_old_status"

_SLA_UPDATE_FIELDS = (
    "sla_due_at",
    "sla_started_at",
    "sla_completed_at",
    "sla_paused_at",
    "sla_paused_seconds",
    "sla_first_breached_at",
    "sla_status",
)


def _persist_sla_fields(instance: Ticket) -> None:
    Ticket.objects.filter(pk=instance.pk).update(
        **{field: getattr(instance, field) for field in _SLA_UPDATE_FIELDS}
    )


@receiver(pre_save, sender=Ticket)
def ticket_pre_save(sender, instance, **kwargs):
    if instance.pk is None:
        return
    try:
        prior = Ticket.objects.only("status").get(pk=instance.pk)
    except Ticket.DoesNotExist:
        return
    setattr(instance, _OLD_STATUS_ATTR, prior.status)


@receiver(post_save, sender=Ticket)
def ticket_post_save(sender, instance, created, **kwargs):
    if created:
        services.on_ticket_created(instance)
        _persist_sla_fields(instance)
        return

    old_status = getattr(instance, _OLD_STATUS_ATTR, None)
    if old_status is None or old_status == instance.status:
        return
    services.on_ticket_status_changed(instance, old_status, instance.status)
    _persist_sla_fields(instance)
