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

WHY IT DOES NOT SEND 288 MESSAGES A DAY
---------------------------------------
The sweep is on the same 5-minute beat as the reconciler, so every
qualifying row qualifies again five minutes later. The cooldown is a
query against the rows the sweep itself wrote: "have I already told this
person about this subject inside the cooldown window?". That is the same
argument `invoicing/tasks.py` makes for the invoice claim — the
idempotency key is the data, not a "did we run today?" flag, because a
flag can be lost, reset, or lie after a partial failure while the log
row cannot.

Keying the cooldown is why `NotificationLog` gained a nullable
`extra_work` FK in W1-B: an Extra Work that has not spawned a ticket has
no `ticket` to key on.

SPRINT W4-Q §1 — THE BELL, AND ONE COOLDOWN FOR BOTH CHANNELS
-------------------------------------------------------------
W1-B sent email and said plainly that it did not do the bell. It does
now: `_emit` writes an in-app `Notification` row and queues the mail
from the SAME recipient list, in the same loop, so the two channels
cannot drift into telling different people. The roster and its tenant
scoping are unchanged — still resolved in `notifications.services`,
still passed through `user_has_scope_for_ticket` on the customer side.

The two channels share ONE cooldown, and a hit on either suppresses
both. The full argument is at `_already_warned_user_ids`; the short
version is that "have I already told this person about this problem
today?" must not have two answers depending on which pipe carried it.

SPRINT W4-Q §2 — THE THRESHOLDS ARE PER COMPANY
-----------------------------------------------
Every number this module compares against used to be one platform-wide
env var. They are now resolved per subject from the SUBJECT'S OWN
company (`sla.thresholds`), falling back to `settings.SLA_WARN_*` where
that company has configured nothing. The env var is the fallback, not
the source of truth, and no deployment had to change for that to be
true: a company with no override row resolves to exactly the numbers it
resolved to before.

The resolver is built once per sweep and asked per row. It is asked with
the subject's own `company_id` every time, never with a value hoisted
out of the loop — a hoisted threshold is one tenant's clock applied to
another tenant's work, which is the tenant-scoping surface of this
sprint and is tested directly.

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
from .thresholds import ThresholdResolver

logger = logging.getLogger(__name__)


#: Ticket statuses that mean "the work has not begun". OPEN is a
#: pre-start live status in `TicketStatus`; REOPENED_BY_ADMIN is a ticket
#: sent back to the start of the loop and equally not being worked.
#: W-FIX1 D6 (audit F27) — ACKNOWLEDGED is "seen and scheduled, not
#: started" (W10), which is precisely the ticket this warning exists
#: for: somebody has promised a start and the start has not happened.
#: It was added to the state machine after this set was written and
#: never joined it, so a scheduled-then-forgotten job never warned.
#: IN_PROGRESS and everything downstream of it HAS started, whatever else
#: may be wrong with it. ON_HOLD is deliberately NOT here: parked work
#: is parked on purpose, and the SLA clock treats it like any other
#: live status (only WAITING_CUSTOMER_APPROVAL pauses it).
NOT_STARTED_TICKET_STATUSES = frozenset(
    {
        TicketStatus.OPEN,
        TicketStatus.REOPENED_BY_ADMIN,
        TicketStatus.ACKNOWLEDGED,
    }
)


def _already_warned_user_ids(
    *, event_type, ticket_id, extra_work_id, user_ids, now, cooldown_hours
):
    """Which of `user_ids` already had THIS warning about THIS subject
    inside the cooldown window. Two queries per emit, not per recipient.

    Sprint W4-Q §1 — ONE COOLDOWN, SHARED BY BOTH CHANNELS.
    ------------------------------------------------------
    The window is asked of the email log AND the in-app feed, and a hit
    on either suppresses both. This is a decision, not an accident, and
    the argument is short: the cooldown answers "have I already told
    this person about this problem today?", and the answer must not
    depend on which pipe carried it. Two independent clocks would let a
    person be told twice about one problem in one day — once in the
    inbox, once in the bell — which is precisely the flood the cooldown
    exists to prevent, arriving through the door we just opened.

    It also makes the throttle self-healing across a partial failure. If
    the mail row is written and the bell row is not (or the reverse),
    the surviving row still holds the window shut, so the next tick five
    minutes later does not re-send the half that worked.

    And it is what would keep a recipient WITHOUT an email address
    safe: they would get the bell only, and the bell row is what
    throttles them. No such recipient reaches `_emit` today — the
    rosters in `notifications.services` still drop address-less users
    upstream (`_active_users` excludes `email=""`) — so this is the
    belt to that braces, not a live path. It costs one query and it
    means the throttle does not depend on a filter three modules away
    staying exactly as it is.
    """
    from notifications.models import Notification, NotificationLog

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
    ids = list(user_ids)
    cutoff = now - datetime.timedelta(hours=int(cooldown_hours))
    warned = set(
        NotificationLog.objects.filter(
            subject_q,
            event_type=event_type,
            recipient_user_id__in=ids,
            created_at__gte=cutoff,
        ).values_list("recipient_user_id", flat=True)
    )
    # The in-app enum's three warning values are spelled identically to
    # the email enum's on purpose (see notifications/models.py), so the
    # same `event_type` string keys both halves of this query.
    warned |= set(
        Notification.objects.filter(
            subject_q,
            event_type=event_type,
            recipient_id__in=ids,
            created_at__gte=cutoff,
        ).values_list("recipient_id", flat=True)
    )
    return warned


def _ring(token, ticket):
    """P-5 S8.1 — the users behind one `also_notify` token, through the
    SAME tenant-scoped rosters the escalation hops use."""
    from notifications.services import (
        company_admin_recipients,
        ticket_assigned_staff_recipients,
        ticket_responsible_manager_recipients,
    )
    from .models import (
        ALSO_NOTIFY_ASSIGNED_STAFF,
        ALSO_NOTIFY_COMPANY_ADMINS,
        ALSO_NOTIFY_RESPONSIBLE_MANAGER,
    )

    if token == ALSO_NOTIFY_ASSIGNED_STAFF:
        return list(ticket_assigned_staff_recipients(ticket))
    if token == ALSO_NOTIFY_RESPONSIBLE_MANAGER:
        return list(ticket_responsible_manager_recipients(ticket))
    if token == ALSO_NOTIFY_COMPANY_ADMINS:
        return list(company_admin_recipients(ticket.company_id))
    return []


def _also_notify(th, warning_key, ticket):
    users = []
    for token in getattr(th, f"{warning_key}_also_notify", ()):
        users += _ring(token, ticket)
    return users


def _elapsed_seconds(th, start, now) -> int:
    """P-5 S8.3 — how long since `start`, in the company's chosen unit:
    working hours (today's rule) or hours on the wall clock."""
    if th.count_calendar_days:
        return max(0, int((now - start).total_seconds()))
    return business_hours.business_seconds_between(start, now)


def _second_warning_moment(th, start, escalate_seconds):
    """When the second warning of an hour-based warning fires, as an
    instant — the anchor the third step counts calendar days from."""
    if th.count_calendar_days:
        return start + datetime.timedelta(seconds=escalate_seconds)
    return business_hours.add_business_seconds(start, escalate_seconds)


def _final_step_reached(th, warning_key, start, escalate_seconds, now) -> bool:
    """P-5 S8.2 — "still not fixed N days after the second warning"."""
    days = getattr(th, f"{warning_key}_final_escalate_days", None)
    if not days:
        return False
    anchor = _second_warning_moment(th, start, escalate_seconds)
    return now >= anchor + datetime.timedelta(days=int(days))


def _extra_email_in_cooldown(
    *, email, event_type, ticket_id, extra_work_id, now, cooldown_hours
):
    from notifications.models import NotificationLog

    since = now - datetime.timedelta(hours=cooldown_hours)
    qs = NotificationLog.objects.filter(
        recipient_email=email, event_type=event_type, created_at__gte=since
    )
    if ticket_id is not None:
        qs = qs.filter(ticket_id=ticket_id)
    elif extra_work_id is not None:
        qs = qs.filter(extra_work_id=extra_work_id)
    return qs.exists()


def _emit(
    *,
    event_type,
    template_key,
    params,
    users,
    now,
    cooldown_hours,
    ticket=None,
    extra_work=None,
    extra_email: str = "",
):
    """Warn everyone in `users` who is not in cooldown, on BOTH channels.

    P-16 Part D — the words come from the notification copy catalogue:
    `template_key` + `params` instead of pre-rendered text. The mail is
    rendered per RECIPIENT language at send time (the log keeps the
    rendered text as the audit record); the bell row stores the key +
    params so the feed re-renders per VIEWER. The extra address is a
    mailbox, not a person, and gets the Dutch rendering.

    Returns the number of PEOPLE warned — not the number of messages,
    because one person now receives two of them. Recipients are deduped
    by id here as well as by the resolvers, because the responsible ring
    and the escalation ring legitimately overlap (a building manager can
    be both) and nobody should get the same warning twice in one tick.

    The bell row and the mail are written from the SAME list, in the
    same loop, so the two channels cannot drift into telling different
    people. Neither is assembled here: the roster arrived already
    tenant-scoped from `notifications.services`, and the bell row is
    written by `notifications.services.emit_sla_warning_inapp`.

    The email address is required for the MAIL only, not for the bell.
    That is a change from W1-B, which dropped an address-less user
    before the send and so gave them nothing at all. It is currently a
    difference without a case: the rosters upstream in
    `notifications.services` already exclude `email=""`, so nobody
    reaches here without one. It is written this way so the bell does
    not silently inherit an email-era assumption from a filter three
    modules away.
    """
    from notifications import copy as notification_copy
    from notifications.services import emit_sla_warning_inapp, send_logged_email

    seen = set()
    candidates = []
    for user in users:
        if not user or not user.id:
            continue
        if user.id in seen:
            continue
        seen.add(user.id)
        candidates.append(user)
    # P-5 S8.1 — the extra address is a mailbox, not a person: mail
    # only, under the same cooldown, logged like every other send.
    extra_sent = 0
    if extra_email and not _extra_email_in_cooldown(
        email=extra_email,
        event_type=event_type,
        ticket_id=getattr(ticket, "id", None),
        extra_work_id=getattr(extra_work, "id", None),
        now=now,
        cooldown_hours=cooldown_hours,
    ):
        subject, body = notification_copy.render_email(template_key, params, "nl")
        send_logged_email(
            recipient_email=extra_email,
            recipient_user=None,
            subject=subject,
            body=body,
            event_type=event_type,
            ticket=ticket,
            extra_work=extra_work,
            template_key=template_key,
            params=params,
        )
        extra_sent = 1
    if not candidates:
        return extra_sent

    suppressed = _already_warned_user_ids(
        event_type=event_type,
        ticket_id=getattr(ticket, "id", None),
        extra_work_id=getattr(extra_work, "id", None),
        user_ids=[u.id for u in candidates],
        now=now,
        cooldown_hours=cooldown_hours,
    )
    warned = [u for u in candidates if u.id not in suppressed]
    if not warned:
        return extra_sent

    emit_sla_warning_inapp(
        event_type=event_type,
        recipients=warned,
        template_key=template_key,
        params=params,
        ticket=ticket,
        extra_work=extra_work,
    )
    for user in warned:
        if not getattr(user, "email", ""):
            continue
        lang = notification_copy.resolve_lang(getattr(user, "language", "nl"))
        subject, body = notification_copy.render_email(template_key, params, lang)
        send_logged_email(
            recipient_email=user.email,
            recipient_user=user,
            subject=subject,
            body=body,
            event_type=event_type,
            ticket=ticket,
            extra_work=extra_work,
            template_key=template_key,
            params=params,
        )
    return len(warned) + extra_sent


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


def sweep_approval_cutoff(now, thresholds):
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
            # Sprint W4-Q §2 — the numbers are the TICKET'S OWN
            # company's. Resolved per subject rather than once per
            # sweep, because the sweep crosses every tenant and a
            # hoisted variable would be one company's clock applied to
            # everybody's work.
            th = thresholds.for_company(ticket.company_id)
            warn_days = th.approval_cutoff_days
            escalate_days = th.approval_cutoff_escalate_days
            cutoff = _billing_cutoff_date(customer, today)
            if cutoff is None:
                continue
            days_left = (cutoff - today).days
            if days_left > warn_days:
                continue
            ew = ticket.extra_work_request
            # P-16 Part D — facts only; the words live in the catalogue.
            params = {
                "ticket_no": ticket.ticket_no,
                "ticket_title": ticket.title,
                "ew_title": ew.title,
                "cutoff_iso": cutoff.isoformat(),
                "days_left": days_left,
            }
            recipients = list(ticket_customer_recipients(ticket))
            # P-5 S8.1 — the rings this company added to the first warning.
            recipients += _also_notify(th, "approval_cutoff", ticket)
            if days_left <= escalate_days:
                # The ONE hop: the provider side that can chase the
                # customer, or record the decision on their behalf.
                recipients += list(ticket_responsible_manager_recipients(ticket))
            # P-5 S8.2 — the third step counts calendar days past the
            # second warning's day; the cutoff may already be behind us.
            final_days = th.approval_cutoff_final_escalate_days
            if final_days and days_left <= escalate_days - int(final_days):
                from notifications.services import company_admin_recipients

                recipients += list(company_admin_recipients(ticket.company_id))
            sent += _emit(
                event_type=NotificationEventType.SLA_APPROVAL_CUTOFF_DUE,
                extra_email=th.approval_cutoff_extra_email,
                template_key="sla_approval_cutoff",
                params=params,
                users=recipients,
                now=now,
                cooldown_hours=th.cooldown_hours,
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

def sweep_manager_review(now, thresholds):
    """Staff said done; nobody has checked it."""
    from notifications.models import NotificationEventType
    from notifications.services import (
        company_admin_recipients,
        ticket_responsible_manager_recipients,
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
            th = thresholds.for_company(ticket.company_id)
            target = th.manager_review_business_seconds
            escalate_target = th.manager_review_escalate_business_seconds
            waited = _elapsed_seconds(th, ticket.manager_review_at, now)
            if waited < target:
                continue
            hours = waited // 3600
            params = {
                "ticket_no": ticket.ticket_no,
                "ticket_title": ticket.title,
                "hours": hours,
            }
            recipients = list(ticket_responsible_manager_recipients(ticket))
            recipients += _also_notify(th, "manager_review", ticket)
            if waited >= escalate_target or _final_step_reached(
                th, "manager_review", ticket.manager_review_at, escalate_target, now
            ):
                # The ONE hop (and P-5 S8.2's third step, same ring).
                recipients += list(company_admin_recipients(ticket.company_id))
            sent += _emit(
                event_type=NotificationEventType.SLA_MANAGER_REVIEW_OVERDUE,
                extra_email=th.manager_review_extra_email,
                template_key="sla_manager_review",
                params=params,
                users=recipients,
                now=now,
                cooldown_hours=th.cooldown_hours,
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

def sweep_not_started_tickets(now, thresholds):
    from notifications.models import NotificationEventType
    from notifications.services import (
        ticket_assigned_staff_recipients,
        ticket_responsible_manager_recipients,
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
            th = thresholds.for_company(ticket.company_id)
            target = th.not_started_business_seconds
            escalate_target = th.not_started_escalate_business_seconds
            late = _elapsed_seconds(th, ticket.scheduled_start_at, now)
            if late < target:
                continue
            hours = late // 3600
            planned = timezone.localtime(ticket.scheduled_start_at)
            params = {
                "ticket_no": ticket.ticket_no,
                "ticket_title": ticket.title,
                "planned_label": planned.strftime("%d-%m-%Y %H:%M"),
                "hours": hours,
            }
            recipients = list(ticket_assigned_staff_recipients(ticket))
            recipients += _also_notify(th, "not_started", ticket)
            if not recipients or late >= escalate_target:
                # The ONE hop: nobody assigned, or the escalation reached.
                recipients += list(ticket_responsible_manager_recipients(ticket))
            if _final_step_reached(
                th, "not_started", ticket.scheduled_start_at, escalate_target, now
            ):
                from notifications.services import company_admin_recipients

                recipients += list(company_admin_recipients(ticket.company_id))
            sent += _emit(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED,
                extra_email=th.not_started_extra_email,
                template_key="sla_not_started_ticket",
                params=params,
                users=recipients,
                now=now,
                cooldown_hours=th.cooldown_hours,
                ticket=ticket,
            )
        except Exception:  # noqa: BLE001 — one ticket must not stop the sweep.
            failed += 1
            logger.exception(
                "sla.warnings: not-started warning failed for ticket %s",
                ticket.pk,
            )
    return sent, failed


def sweep_not_started_extra_work(now, thresholds):
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
            th = thresholds.for_company(ew.company_id)
            late = business_hours.business_seconds_between(planned_at, now)
            if late < th.not_started_business_seconds:
                continue
            hours = late // 3600
            # `ew_ref` is the reference the subject line prints — the
            # EW's number is its only human handle (it has no ticket_no
            # sibling), frozen into the params as a label.
            params = {
                "ew_title": ew.title,
                "ew_ref": f"Meerwerk #{ew.pk}",
                "planned_iso": ew.provider_planned_date.isoformat(),
                "hours": hours,
            }
            # An Extra Work has no per-row responsible-manager table and
            # no crew until a ticket is spawned, so provider management
            # IS the responsible ring here. There is no second hop above
            # it that is not the same people.
            sent += _emit(
                event_type=NotificationEventType.SLA_WORK_NOT_STARTED,
                template_key="sla_not_started_extra_work",
                params=params,
                users=list(extra_work_provider_recipients(ew)),
                now=now,
                cooldown_hours=th.cooldown_hours,
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

    # Sprint W4-Q §2 — every threshold below is now the SUBJECT'S OWN
    # company's, falling back to `settings.SLA_WARN_*` where that
    # company has configured nothing. The resolver is built once per
    # sweep (one query for every override row) and asked per subject;
    # building it here rather than inside the four sweeps means one
    # query per tick instead of four.
    thresholds = ThresholdResolver()

    cutoff_sent, cutoff_failed = sweep_approval_cutoff(now, thresholds)
    review_sent, review_failed = sweep_manager_review(now, thresholds)
    ticket_sent, ticket_failed = sweep_not_started_tickets(now, thresholds)
    ew_sent, ew_failed = sweep_not_started_extra_work(now, thresholds)

    return {
        "approval_cutoff": cutoff_sent,
        "manager_review": review_sent,
        "not_started_tickets": ticket_sent,
        "not_started_extra_work": ew_sent,
        "failed": cutoff_failed + review_failed + ticket_failed + ew_failed,
    }
