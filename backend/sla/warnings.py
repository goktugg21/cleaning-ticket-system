"""
Sprint W1-B §2.7 — the time-driven warnings, and the ONE escalation hop.

WHAT WAS MISSING
----------------
`sla/` has run every five minutes over every non-terminal ticket since
Sprint 7, with real business-hours arithmetic, and notified NOBODY. It
wrote `Ticket.sla_status` and stopped. On the other side, all nine
members of `NotificationEventType` were event-driven: somebody did
something, somebody was told. "Nothing happened and it should have" was
an empty category, and nothing escalated to anyone's manager.

This module is that category. It does NOT build a second engine: the
business-hours maths is `sla.business_hours`, the sender is
`notifications.services.send_logged_email`, and the rosters are the
tenant-scoped resolvers in `notifications.services` — reused, not
re-derived, because a second copy of "who may hear about this" is how a
cross-tenant leak gets written.

THREE WARNINGS
--------------
1. `SLA_APPROVAL_CUTOFF_DUE` — work is finished and sitting with the
   customer while their billing cutoff approaches. Under the cutoff rule
   (`extra_work.billing.is_earned`) it WILL be invoiced on that date
   whether or not their approval has landed. This warning is what makes
   that rule fair rather than a surprise, so it is the one warning whose
   first recipient is the customer.
   RESPONSIBLE: the customer's own people. HOP: the provider managers
   answerable for the ticket, who are the ones who can chase.

2. `SLA_MANAGER_REVIEW_OVERDUE` — staff said "done" and a provider
   manager has not checked it. Deliberately its own warning rather than
   folded into the SLA clock, because `sla.services` treats
   WAITING_MANAGER_REVIEW as a perfectly ordinary live state and the
   ticket can sit there indefinitely inside a green SLA.
   RESPONSIBLE: the responsible managers. HOP: the company admins.

3. `SLA_WORK_NOT_STARTED` — the planned start has passed and nothing
   has started. Covers BOTH tickets (`scheduled_start_at`) and Extra
   Work (`provider_planned_date`), which is the Extra Work clock: the
   existing `reconcile_sla_states` iterates `Ticket` only, and an Extra
   Work that has not spawned an operational ticket yet has no clock at
   all today.
   RESPONSIBLE: the assigned staff (provider management, for an Extra
   Work with no crew on it yet). HOP: the responsible managers.

WHY NOT THE PAUSED SLA CLOCK FOR (1)
------------------------------------
`sla.services.PAUSED_STATUS` IS `WAITING_CUSTOMER_APPROVAL` — the SLA
clock stops the moment work reaches the customer, deliberately, because
the provider is not answerable for the customer's response time. So the
SLA status can never express "the customer is about to be billed". The
cutoff warning reads the billing calendar instead
(`invoicing.schedule.effective_billing_day`), which is the same rule the
invoice run itself fires on. One definition of the cutoff, two readers.

ONE HOP, NOT A CHAIN
--------------------
Every warning has TWO thresholds. The first notifies the responsible
person. The second, larger one ALSO notifies the single hop above them.
There is no third. Nothing here re-escalates, re-times, or walks a
reporting tree — the settings are two numbers per warning and the code
is one `if`.

WHY IT DOES NOT SEND 288 MAILS A DAY
------------------------------------
The sweep is on the same 5-minute beat as the reconciler, so every
qualifying row qualifies again five minutes later. The cooldown is a
query against the `NotificationLog` rows the sweep itself wrote:
"have I already told this person about this subject inside
SLA_WARN_COOLDOWN_HOURS?". That is the same argument `invoicing/tasks.py`
makes for the invoice claim — the idempotency key is the data, not a
"did we run today?" flag, because a flag can be lost, reset, or lie after
a partial failure while the log row cannot.

Keying the cooldown is why `NotificationLog` gained a nullable
`extra_work` FK this sprint: an Extra Work that has not spawned a ticket
has no `ticket` to key on.

TENANT SCOPING
--------------
Every roster is resolved from the subject row's OWN company / building /
customer FKs via `notifications.services`, and the customer roster is
additionally passed through `user_has_scope_for_ticket`. A warning can
never reach a user in another company, and never reaches a customer user
who could not open the thing it is about.

NEVER FATAL
-----------
A warning that raises must not take the sweep down with it, and must
never take down a beat tick shared with anything else. Each subject is
tried independently and a failure is logged and counted.
"""
from __future__ import annotations

import datetime
import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from . import business_hours

logger = logging.getLogger(__name__)


#: Ticket statuses that mean "the work has not begun". OPEN is the only
#: pre-start live status in `TicketStatus`; REOPENED_BY_ADMIN is a ticket
#: sent back to the start of the loop and equally not being worked.
#: IN_PROGRESS and everything downstream of it HAS started, whatever else
#: may be wrong with it.
NOT_STARTED_TICKET_STATUSES = frozenset(
    {
        TicketStatus.OPEN,
        TicketStatus.REOPENED_BY_ADMIN,
    }
)


def _cooldown_cutoff(now):
    hours = int(getattr(settings, "SLA_WARN_COOLDOWN_HOURS", 24))
    return now - datetime.timedelta(hours=hours)


def _already_warned_user_ids(*, event_type, ticket_id, extra_work_id, user_ids, now):
    """Which of `user_ids` already had THIS warning about THIS subject
    inside the cooldown window. One query per emit, not per recipient."""
    from notifications.models import NotificationLog

    if not user_ids:
        return set()
    subject_q = Q()
    if ticket_id is not None:
        subject_q |= Q(ticket_id=ticket_id)
    if extra_work_id is not None:
        subject_q |= Q(extra_work_id=extra_work_id)
    if not subject_q:
        # No subject key at all — refuse to send rather than send
        # unthrottled. An un-keyed warning is a warning that repeats
        # every five minutes forever.
        return set(user_ids)
    return set(
        NotificationLog.objects.filter(
            subject_q,
            event_type=event_type,
            recipient_user_id__in=list(user_ids),
            created_at__gte=_cooldown_cutoff(now),
        ).values_list("recipient_user_id", flat=True)
    )


def _emit(*, event_type, subject, body, users, now, ticket=None, extra_work=None):
    """Send one warning to everyone in `users` who is not in cooldown.

    Returns the number of mails actually queued. Recipients are deduped
    by id here as well as by the resolvers, because the responsible ring
    and the escalation ring legitimately overlap (a building manager can
    be both) and nobody should get the same warning twice in one tick.
    """
    from notifications.services import send_logged_email

    seen = set()
    candidates = []
    for user in users:
        if not user or not user.id or not getattr(user, "email", ""):
            continue
        if user.id in seen:
            continue
        seen.add(user.id)
        candidates.append(user)
    if not candidates:
        return 0

    suppressed = _already_warned_user_ids(
        event_type=event_type,
        ticket_id=getattr(ticket, "id", None),
        extra_work_id=getattr(extra_work, "id", None),
        user_ids=[u.id for u in candidates],
        now=now,
    )
    sent = 0
    for user in candidates:
        if user.id in suppressed:
            continue
        send_logged_email(
            recipient_email=user.email,
            recipient_user=user,
            subject=subject,
            body=body,
            event_type=event_type,
            ticket=ticket,
            extra_work=extra_work,
        )
        sent += 1
    return sent


def _sign_off():
    return [
        "",
        "Met vriendelijke groet,",
        "het CleanOps-team",
        "",
        "Deze e-mail is automatisch verzonden. U kunt niet rechtstreeks "
        "reageren op dit bericht.",
    ]


# ---------------------------------------------------------------------------
# 1. Approval due before the billing cutoff
# ---------------------------------------------------------------------------

def _billing_cutoff_date(customer, on_or_after):
    """The customer's NEXT billing cutoff on or after `on_or_after`, or
    None when they have no billing schedule.

    Reads `invoicing.schedule.effective_billing_day` — the same function
    the /due/ panel and the nightly invoice run resolve the billing day
    with. A customer with no schedule is never automatically invoiced, so
    there is no cutoff to warn about and this returns None rather than
    guessing a date.
    """
    from invoicing.schedule import effective_billing_day

    year, month = on_or_after.year, on_or_after.month
    for _ in range(2):
        day = effective_billing_day(customer, year=year, month=month)
        if day is None:
            return None
        try:
            candidate = datetime.date(year, month, day)
        except ValueError:  # pragma: no cover — day is capped at 28/real last
            return None
        if candidate >= on_or_after:
            return candidate
        # This month's cutoff has passed; the next one is next month's.
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def sweep_approval_cutoff(now):
    """Finished Extra Work sitting with the customer as their cutoff nears.

    Restricted to tickets spawned from an Extra Work, and to Extra Work
    that is still billable and unclaimed. A plain melding awaiting a
    customer's sign-off has no invoice attached to it, so there is no
    cutoff for it to miss and warning about it would be noise.
    """
    from extra_work.billing import NON_BILLABLE_STATUSES
    from notifications.models import NotificationEventType
    from notifications.services import (
        ticket_customer_recipients,
        ticket_responsible_manager_recipients,
    )

    warn_days = int(getattr(settings, "SLA_WARN_APPROVAL_CUTOFF_DAYS", 5))
    escalate_days = int(
        getattr(settings, "SLA_WARN_APPROVAL_CUTOFF_ESCALATE_DAYS", 2)
    )
    today = timezone.localtime(now).date()

    qs = (
        Ticket.objects.filter(
            status=TicketStatus.WAITING_CUSTOMER_APPROVAL,
            deleted_at__isnull=True,
            sent_for_approval_at__isnull=False,
            extra_work_request__isnull=False,
            extra_work_request__deleted_at__isnull=True,
            extra_work_request__is_invoiced=False,
        )
        .exclude(extra_work_request__status__in=list(NON_BILLABLE_STATUSES))
        .select_related("customer", "extra_work_request")
        .order_by("id")
    )

    sent = failed = 0
    for ticket in qs.iterator():
        try:
            customer = ticket.customer
            if customer is None:
                continue
            cutoff = _billing_cutoff_date(customer, today)
            if cutoff is None:
                continue
            days_left = (cutoff - today).days
            if days_left > warn_days:
                continue
            ew = ticket.extra_work_request
            cutoff_label = cutoff.strftime("%d-%m-%Y")
            subject = (
                f"[{ticket.ticket_no}] Uw goedkeuring wordt verwacht voor "
                f"de facturatiedatum {cutoff_label}"
            )
            body = "\n".join(
                [
                    "Het werk hieronder is afgerond en wacht op uw goedkeuring.",
                    "",
                    f"Uw facturatiedatum is {cutoff_label} "
                    f"(over {days_left} dag(en)).",
                    "",
                    "Belangrijk: werk dat vóór uw facturatiedatum is "
                    "afgerond, komt op de eerstvolgende factuur te staan, "
                    "ook als uw goedkeuring dan nog niet binnen is. Zo "
                    "staat het werk op de factuur van de maand waarin het "
                    "echt is uitgevoerd.",
                    "",
                    "Bent u het niet eens met het werk? Keur het dan af of "
                    "neem contact op met uw beheerder. Is het al "
                    "gefactureerd, dan draaien wij de factuur terug met een "
                    "creditnota en verdwijnt het werk weer van uw rekening.",
                    "",
                    f"Extra werk: {ew.title}",
                    f"Ticket: {ticket.ticket_no} - {ticket.title}",
                ]
                + _sign_off()
            )
            recipients = list(ticket_customer_recipients(ticket))
            if days_left <= escalate_days:
                # The ONE hop: the provider side that can chase the
                # customer, or record the decision on their behalf
                # through the existing reasoned override.
                recipients += list(ticket_responsible_manager_recipients(ticket))
            sent += _emit(
                event_type=NotificationEventType.SLA_APPROVAL_CUTOFF_DUE,
                subject=subject,
                body=body,
                users=recipients,
                now=now,
                ticket=ticket,
                extra_work=ew,
            )
        except Exception:  # noqa: BLE001 — one ticket must not stop the sweep.
            failed += 1
            logger.exception(
                "sla.warnings: approval-cutoff warning failed for ticket %s",
                ticket.pk,
            )
    return sent, failed


# ---------------------------------------------------------------------------
# 2. Manager review past its target
# ---------------------------------------------------------------------------

def sweep_manager_review(now):
    """Staff said done; nobody has checked it."""
    from notifications.models import NotificationEventType
    from notifications.services import (
        company_admin_recipients,
        ticket_responsible_manager_recipients,
    )

    target = int(
        getattr(settings, "SLA_WARN_MANAGER_REVIEW_BUSINESS_SECONDS", 8 * 3600)
    )
    escalate_target = int(
        getattr(
            settings,
            "SLA_WARN_MANAGER_REVIEW_ESCALATE_BUSINESS_SECONDS",
            24 * 3600,
        )
    )

    qs = (
        Ticket.objects.filter(
            status=TicketStatus.WAITING_MANAGER_REVIEW,
            deleted_at__isnull=True,
            manager_review_at__isnull=False,
        )
        .order_by("id")
    )

    sent = failed = 0
    for ticket in qs.iterator():
        try:
            waited = business_hours.business_seconds_between(
                ticket.manager_review_at, now
            )
            if waited < target:
                continue
            hours = waited // 3600
            subject = (
                f"[{ticket.ticket_no}] Wacht op uw controle "
                f"({hours} werkuren)"
            )
            body = "\n".join(
                [
                    "Een medewerker heeft dit werk als uitgevoerd gemeld. "
                    "Het wacht nu op uw controle en is nog niet naar de "
                    "klant gestuurd.",
                    "",
                    f"Wachttijd: {hours} werkuren.",
                    "",
                    "Zolang het hier staat, ziet de klant het niet en kan "
                    "het niet gefactureerd worden.",
                    "",
                    f"Ticket: {ticket.ticket_no} - {ticket.title}",
                ]
                + _sign_off()
            )
            recipients = list(ticket_responsible_manager_recipients(ticket))
            if waited >= escalate_target:
                # The ONE hop above a building manager.
                recipients += list(company_admin_recipients(ticket.company_id))
            sent += _emit(
                event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
                subject=subject,
                body=body,
                users=recipients,
                now=now,
                ticket=ticket,
            )
        except Exception:  # noqa: BLE001 — one ticket must not stop the sweep.
            failed += 1
            logger.exception(
                "sla.warnings: manager-review warning failed for ticket %s",
                ticket.pk,
            )
    return sent, failed


# ---------------------------------------------------------------------------
# 3. Should have started and has not — tickets AND Extra Work
# ---------------------------------------------------------------------------

def sweep_not_started_tickets(now):
    from notifications.models import NotificationEventType
    from notifications.services import (
        ticket_assigned_staff_recipients,
        ticket_responsible_manager_recipients,
    )

    target = int(
        getattr(settings, "SLA_WARN_NOT_STARTED_BUSINESS_SECONDS", 4 * 3600)
    )
    escalate_target = int(
        getattr(
            settings, "SLA_WARN_NOT_STARTED_ESCALATE_BUSINESS_SECONDS", 16 * 3600
        )
    )

    qs = (
        Ticket.objects.filter(
            status__in=list(NOT_STARTED_TICKET_STATUSES),
            deleted_at__isnull=True,
            scheduled_start_at__isnull=False,
            scheduled_start_at__lt=now,
        )
        .order_by("id")
    )

    sent = failed = 0
    for ticket in qs.iterator():
        try:
            late = business_hours.business_seconds_between(
                ticket.scheduled_start_at, now
            )
            if late < target:
                continue
            hours = late // 3600
            planned = timezone.localtime(ticket.scheduled_start_at)
            subject = (
                f"[{ticket.ticket_no}] Nog niet gestart "
                f"({hours} werkuren na de planning)"
            )
            body = "\n".join(
                [
                    "Dit werk had moeten beginnen en staat nog steeds op "
                    "niet gestart.",
                    "",
                    f"Geplande start: {planned.strftime('%d-%m-%Y %H:%M')}.",
                    f"Verstreken: {hours} werkuren.",
                    "",
                    f"Ticket: {ticket.ticket_no} - {ticket.title}",
                ]
                + _sign_off()
            )
            recipients = list(ticket_assigned_staff_recipients(ticket))
            if not recipients or late >= escalate_target:
                # No crew on it at all is itself a management problem, so
                # the hop fires immediately in that case; otherwise it
                # waits for the second threshold. Still ONE hop.
                recipients += list(ticket_responsible_manager_recipients(ticket))
            sent += _emit(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED,
                subject=subject,
                body=body,
                users=recipients,
                now=now,
                ticket=ticket,
            )
        except Exception:  # noqa: BLE001 — one ticket must not stop the sweep.
            failed += 1
            logger.exception(
                "sla.warnings: not-started warning failed for ticket %s",
                ticket.pk,
            )
    return sent, failed


def sweep_not_started_extra_work(now):
    """The Extra Work clock.

    `reconcile_sla_states` iterates `Ticket` only, so an Extra Work that
    is approved and planned but has not spawned an operational ticket yet
    has no clock at all — it can sit past its planned start forever with
    nothing anywhere going amber. This is that clock, measured the same
    way (business hours) against `provider_planned_date`, the date the
    provider committed to.

    Deliberately anchored on `provider_planned_date` and NOT on the
    customer's `preferred_date` / `deadline`: those are what the customer
    ASKED for, and warning the provider for missing a date they never
    agreed to would make the whole warning family untrustworthy.

    Only CUSTOMER_APPROVED rows qualify — IN_PROGRESS and COMPLETED have
    started, and everything before CUSTOMER_APPROVED is not yet work
    anybody committed to a date on.

    NOTE: this reads a date, not a time. `provider_planned_date` is a
    DateField, so "the planned start" is taken as the START of the
    business window on that day.
    """
    from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
    from notifications.models import NotificationEventType
    from notifications.services import extra_work_provider_recipients

    target = int(
        getattr(settings, "SLA_WARN_NOT_STARTED_BUSINESS_SECONDS", 4 * 3600)
    )
    today = timezone.localtime(now).date()
    tz = business_hours.project_tz()
    window_start = datetime.time(*settings.SLA_BUSINESS_HOURS_START)

    qs = (
        ExtraWorkRequest.objects.filter(
            status=ExtraWorkStatus.CUSTOMER_APPROVED,
            deleted_at__isnull=True,
            provider_planned_date__isnull=False,
            provider_planned_date__lte=today,
        )
        .order_by("id")
    )

    sent = failed = 0
    for ew in qs.iterator():
        try:
            planned_at = datetime.datetime.combine(
                ew.provider_planned_date, window_start, tzinfo=tz
            )
            if planned_at >= now:
                continue
            late = business_hours.business_seconds_between(planned_at, now)
            if late < target:
                continue
            hours = late // 3600
            planned_label = ew.provider_planned_date.strftime("%d-%m-%Y")
            subject = (
                f"[Extra werk #{ew.pk}] Nog niet gestart "
                f"(gepland op {planned_label})"
            )
            body = "\n".join(
                [
                    "Dit extra werk is goedgekeurd en ingepland, maar er is "
                    "nog geen uitvoering gestart.",
                    "",
                    f"Geplande datum: {planned_label}.",
                    f"Verstreken: {hours} werkuren.",
                    "",
                    f"Extra werk: {ew.title}",
                ]
                + _sign_off()
            )
            # An Extra Work has no per-row responsible-manager table and
            # no crew until a ticket is spawned, so provider management
            # IS the responsible ring here. There is no second hop above
            # it that is not the same people.
            sent += _emit(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED,
                subject=subject,
                body=body,
                users=list(extra_work_provider_recipients(ew)),
                now=now,
                extra_work=ew,
            )
        except Exception:  # noqa: BLE001 — one EW must not stop the sweep.
            failed += 1
            logger.exception(
                "sla.warnings: not-started warning failed for extra work %s",
                ew.pk,
            )
    return sent, failed


def sweep(now=None) -> dict:
    """Run all three warnings. Idempotent within the cooldown window.

    `now` exists for tests and for an operator re-running a missed window
    by hand; the beat schedule never passes it.
    """
    if now is None:
        now = timezone.now()

    cutoff_sent, cutoff_failed = sweep_approval_cutoff(now)
    review_sent, review_failed = sweep_manager_review(now)
    ticket_sent, ticket_failed = sweep_not_started_tickets(now)
    ew_sent, ew_failed = sweep_not_started_extra_work(now)

    return {
        "approval_cutoff": cutoff_sent,
        "manager_review": review_sent,
        "not_started_tickets": ticket_sent,
        "not_started_extra_work": ew_sent,
        "failed": cutoff_failed + review_failed + ticket_failed + ew_failed,
    }
