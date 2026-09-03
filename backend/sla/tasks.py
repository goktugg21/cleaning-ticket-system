"""
Periodic SLA reconciliation. Wired in CELERY_BEAT_SCHEDULE in settings.py to
run every 5 minutes via the dedicated `beat` container in docker-compose.

Sprint W1-B §2.7 adds a SECOND task on the same beat: `sweep_sla_warnings`,
which is the half that talks to people. `reconcile_sla_states` measures and
writes a column; the sweep reads clocks and sends mail. They are kept as two
tasks rather than one because they fail differently — a reconciler that dies
leaves stale statuses, a sweep that dies leaves silence — and because a
future operator will want to disable one without the other.
"""
import logging

from celery import shared_task
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

from . import services

logger = logging.getLogger(__name__)


_NON_TERMINAL_STATUSES = [
    s for s in TicketStatus.values
    # Sprint 7B — CONVERTED_TO_EXTRA_WORK is terminal: SLA reconciliation
    # must treat a converted ticket as done and stop touching its clock.
    if s
    not in (
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
        TicketStatus.CLOSED,
        TicketStatus.CONVERTED_TO_EXTRA_WORK,
    )
]


@shared_task
def reconcile_sla_states():
    """Update sla_status across all live tickets. Idempotent."""
    now = timezone.now()
    base_qs = Ticket.objects.filter(
        status__in=_NON_TERMINAL_STATUSES,
    ).exclude(sla_status="HISTORICAL")
    checked = base_qs.count()

    fields = [
        "id", "status", "sla_started_at", "sla_due_at", "sla_paused_at",
        "sla_paused_seconds", "sla_first_breached_at", "sla_status",
    ]
    updated = 0
    for ticket in base_qs.only(*fields).iterator():
        if services.reconcile(ticket, now=now):
            Ticket.objects.filter(pk=ticket.pk).update(
                sla_status=ticket.sla_status,
                sla_first_breached_at=ticket.sla_first_breached_at,
            )
            updated += 1
    return {"checked": checked, "updated": updated}


@shared_task
def sweep_sla_warnings(now=None):
    """Emit the three time-driven warnings. See `sla/warnings.py`.

    Never raises: this shares a beat with nothing today, but a periodic
    task that dies on one bad row stops warning about every other row too
    — which is the exact silence this sprint exists to end. Per-subject
    failures are already caught inside the sweep and counted in
    `failed`; this outer guard covers a failure of the sweep itself.

    `now` (an ISO datetime string) exists for tests and for an operator
    re-running a missed window by hand; the beat schedule never passes it.
    """
    from datetime import datetime

    from . import warnings as sla_warnings

    when = datetime.fromisoformat(now) if now else timezone.now()
    try:
        return sla_warnings.sweep(now=when)
    except Exception:  # noqa: BLE001 — never let one tick kill the schedule.
        logger.exception("sla.tasks: warning sweep failed")
        return {
            "approval_cutoff": 0,
            "manager_review": 0,
            "not_started_tickets": 0,
            "not_started_extra_work": 0,
            "failed": 1,
        }


# P-5 S8.4 — THE WEEKLY LIST.
#
# "Mail the admins a weekly list of every warning sent." Reuses the
# digest shape `invoicing.tasks.send_billing_month_at_risk_digest`
# established: per company, one plain-text mail per admin, through the
# ONE logged sender, never raising. Off by default; the company's row
# switches it on (`weekly_summary_enabled`).
SLA_EVENT_TYPES = (
    "SLA_APPROVAL_CUTOFF_DUE",
    "SLA_MANAGER_REVIEW_OVERDUE",
    "SLA_WORK_NOT_STARTED",
)

def _weekly_summary_params(rows, *, since, until) -> dict:
    """P-16 Part D — the digest's facts, for the copy catalogue. The
    words (labels, framing sentences) live in `notifications/copy.py`;
    this packs each log row into names, numbers and pre-localised
    timestamps."""
    return {
        "since_iso": since.isoformat(),
        "until_iso": until.isoformat(),
        "rows": [
            {
                "event_type": row.event_type,
                "when": timezone.localtime(row.created_at).strftime(
                    "%d-%m %H:%M"
                ),
                "subject": row.subject,
                "recipient": row.recipient_email,
            }
            for row in rows
        ],
    }


def weekly_summary_body(rows, *, since, until) -> str:
    """The Dutch rendering, kept as a callable seam for the tests that
    pin the digest's shape."""
    from notifications import copy as notification_copy

    _, body = notification_copy.render_email(
        "sla_weekly_summary",
        _weekly_summary_params(rows, since=since, until=until),
        "nl",
    )
    return body


@shared_task
def send_sla_weekly_summary(now=None):
    """Monday morning: per company with `weekly_summary_enabled`, mail
    every company admin the list of SLA warnings logged in the past
    seven days. Returns `{"companies": n, "mails": m, "failed": f}`."""
    from datetime import datetime, timedelta

    from django.db.models import Q

    from notifications.models import NotificationEventType, NotificationLog
    from notifications.services import company_admin_recipients, send_logged_email

    from .models import SlaWarningThreshold

    when = datetime.fromisoformat(now) if now else timezone.now()
    until = timezone.localtime(when).date()
    since = until - timedelta(days=7)
    companies = mails = failed = 0
    for row in SlaWarningThreshold.objects.filter(weekly_summary_enabled=True):
        try:
            companies += 1
            logs = list(
                NotificationLog.objects.filter(
                    event_type__in=SLA_EVENT_TYPES,
                    created_at__gte=when - timedelta(days=7),
                    created_at__lt=when,
                )
                .filter(
                    Q(ticket__company_id=row.company_id)
                    | Q(extra_work__company_id=row.company_id)
                )
                .order_by("event_type", "created_at")
            )
            # P-16 Part D — rendered per RECIPIENT language through the
            # catalogue; the log row keeps the key + facts beside the
            # rendered audit record.
            from notifications import copy as notification_copy

            params = _weekly_summary_params(logs, since=since, until=until)
            for admin in company_admin_recipients(row.company_id):
                lang = notification_copy.resolve_lang(
                    getattr(admin, "language", "nl")
                )
                subject, body = notification_copy.render_email(
                    "sla_weekly_summary", params, lang
                )
                send_logged_email(
                    recipient_email=admin.email,
                    recipient_user=admin,
                    subject=subject,
                    body=body,
                    event_type=NotificationEventType.SLA_WEEKLY_SUMMARY,
                    template_key="sla_weekly_summary",
                    params=params,
                )
                mails += 1
        except Exception:  # noqa: BLE001 — one company must not stop the rest.
            failed += 1
            logger.exception(
                "sla.tasks: weekly summary failed for company %s", row.company_id
            )
    return {"companies": companies, "mails": mails, "failed": failed}
