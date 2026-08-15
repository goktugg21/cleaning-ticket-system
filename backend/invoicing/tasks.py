"""
Sprint 182 §1 — the month-end job.

The owner's father's description IS the specification:

    A job runs daily. First question: is there a customer whose billing
    day is today? If yes, take that customer's COMPLETED extra works,
    group those billed to a building under the building and those billed
    to the customer under the customer, create the draft invoices, mark
    the extra works as invoiced so they do not come up again, then notify
    the admin.

Every clause maps to something here:

  "runs daily"                -> CELERY_BEAT_SCHEDULE, every 24h.
  "billing day is today"      -> `schedule.is_billing_day`, the same rule
                                 the /due/ panel reports.
  "COMPLETED extra works"     -> `selectors.unbilled_extra_work`, which
                                 tests `extra_work.billing.is_earned`.
                                 We do NOT define billable here.
  "group ... under the ..."   -> `preview.plan_invoices`, per-row target.
  "create the draft invoices" -> `services.generate_draft_invoices`.
  "mark ... so they do not
   come up again"             -> the CLAIM inside `_create_draft`.
  "notify the admin"          -> `_notify_run`.

WHAT STOPS IT DOUBLE-CREATING
-----------------------------
Three layers, and only the first is really load-bearing:

1. **The claim.** This is the real one, and it is data, not a flag on the
   run. `_create_draft` sets `is_invoiced=True` on every Extra Work it
   consumes AND links it to the new `InvoiceLine`. `unbilled_extra_work`
   excludes both. So a second run — later the same day, twice in the same
   minute, or after a crash halfway through — finds an empty pool and
   creates nothing. This is the same mechanism the manual `generate`
   button has always relied on; the job does not invent a second one.

   This mirrors `planned_work.generation`, whose idempotency is likewise
   a data constraint (a unique key on the occurrence) rather than "did we
   run today?" bookkeeping. A run-log flag can be lost, reset, or lie
   after a partial failure; the claim cannot, because it IS the thing
   that would be double-created.

2. **The atomic block.** `generate_draft_invoices` wraps creation +
   claim in one `transaction.atomic()`. A failure part-way through rolls
   back both, so there is no invoice holding rows it never claimed and no
   claimed row without an invoice.

3. **Exact-day triggering.** `is_billing_day` fires on the billing day
   only, not "from the billing day onward". Without it the job would
   re-attempt every remaining day of the month — harmless thanks to (1),
   but it would bury a real failure in 20 days of no-op log lines.

What is deliberately NOT here: a "last run" timestamp gate. It would add
a second source of truth about whether the work happened, and the first
time it disagreed with the claim someone would have to work out which one
was lying.

CONCURRENCY: two workers firing the same beat tick would both read the
unbilled pool before either claims. `select_for_update` on the EW rows
would close it. It is NOT done here, because it would mean editing
`extra_work` (Agent A's app this sprint) and because beat delivers one
tick to one worker; the exposure is a duplicate manual `generate` racing
the job, which the operator would see immediately as two drafts. Called
out rather than silently accepted — see the report.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# Sprint 182 §1 — the notification event for a completed invoice run.
#
# Defined HERE rather than added to `notifications.NotificationEventType`
# because `backend/notifications/` is not this agent's file this sprint.
# The value persists and mails correctly (`NotificationLog.event_type` is
# a CharField and `objects.create` does not validate choices), but it is
# outside the enum, so `get_event_type_display()` returns the raw string.
# The one-line fix — adding it to the enum plus an AlterField migration —
# is named in the sprint report.
INVOICE_RUN_EVENT = "INVOICE_RUN_COMPLETED"


def _run_actor(company_id):
    """A provider operator to attribute the run's invoices to.

    `Invoice.created_by` is NOT NULL and PROTECT, so the job needs a real
    user. We pick the company's longest-standing active COMPANY_ADMIN,
    falling back to any active SUPER_ADMIN.

    This is the weakest part of the design and worth naming: the invoices
    say a person created them and no person did. The honest fix is a
    nullable `created_by` meaning "the system", exactly as
    `TicketStatusHistory.changed_by` was made nullable in Sprint 180 — but
    that reads on every invoice serializer, PDF and list in the app, so it
    is a change to make deliberately and not as a side effect of adding a
    task. Returns None when no operator exists, and the caller skips the
    customer rather than inventing one.
    """
    from accounts.models import UserRole
    from companies.models import CompanyUserMembership

    User = _user_model()
    admin = (
        User.objects.filter(
            id__in=CompanyUserMembership.objects.filter(
                company_id=company_id
            ).values_list("user_id", flat=True),
            role=UserRole.COMPANY_ADMIN,
            is_active=True,
            deleted_at__isnull=True,
        )
        .order_by("id")
        .first()
    )
    if admin is not None:
        return admin
    return (
        User.objects.filter(
            role=UserRole.SUPER_ADMIN, is_active=True, deleted_at__isnull=True
        )
        .order_by("id")
        .first()
    )


def _user_model():
    from django.contrib.auth import get_user_model

    return get_user_model()


def _notify_run(actor, customer, invoices):
    """Tell the admin what the run produced for one customer.

    Best-effort: a failed notification must not roll back invoices that
    were correctly created. The run already happened; losing the email is
    an annoyance, losing the invoices is a month of billing.
    """
    from notifications.services import send_logged_email

    if actor is None or not getattr(actor, "email", ""):
        return None
    total = sum((inv.total_amount for inv in invoices), start=0)
    lines = [
        f"De facturatietaak heeft {len(invoices)} conceptfactuur/-facturen "
        f"aangemaakt voor {customer.name}.",
        "",
        f"Totaal: {total:.2f}",
        "",
    ]
    for inv in invoices:
        where = "klantniveau" if inv.building_id is None else "per gebouw"
        lines.append(f"  - concept #{inv.pk} ({where}): {inv.total_amount:.2f}")
    lines += [
        "",
        "Deze concepten zijn nog niet verstuurd; controleer ze in Facturen.",
        "",
        "Deze e-mail is automatisch verzonden.",
    ]
    try:
        return send_logged_email(
            recipient_email=actor.email,
            recipient_user=actor,
            subject=(
                f"[Facturatie] {len(invoices)} concept(en) aangemaakt voor "
                f"{customer.name}"
            ),
            body="\n".join(lines),
            event_type=INVOICE_RUN_EVENT,
        )
    except Exception:  # noqa: BLE001 — never lose invoices over an email.
        logger.exception(
            "Sprint 182 §1: invoice-run notification failed for customer %s",
            customer.pk,
        )
        return None


def run_invoice_run_for_customer(customer, *, year, month, actor=None):
    """Generate this customer's drafts for (year, month) and notify.

    Split out from the task body so a test — or an operator through the
    management command — can drive ONE customer without waiting for a
    beat tick or faking a date.

    Returns the list of created invoices (empty when there was nothing
    unbilled, which is the normal repeat-run outcome).
    """
    from .services import generate_draft_invoices

    actor = actor or _run_actor(customer.company_id)
    if actor is None:
        logger.warning(
            "Sprint 182 §1: no provider operator for company %s; skipping "
            "customer %s. Invoice.created_by is NOT NULL, so the run cannot "
            "attribute invoices without one.",
            customer.company_id,
            customer.pk,
        )
        return []

    created = generate_draft_invoices(
        actor, customer.company_id, customer.id, year, month
    )
    if created:
        _notify_run(actor, customer, created)
    return created


@shared_task
def run_daily_invoice_run(today=None):
    """The daily driver. Whose billing day is today?

    `today` (an ISO date string) exists for tests and for an operator
    re-running a missed day by hand; the beat schedule never passes it.

    Never raises: one customer's failure must not stop the rest of the
    run. A customer that raised is counted in `failed` and logged with a
    traceback — the run reports what it could not do rather than dying at
    the first problem and leaving the remaining customers silently
    unbilled.
    """
    from datetime import date

    from django.utils import timezone

    from customers.models import Customer

    from .schedule import is_billing_day, scheduled_customers

    day = date.fromisoformat(today) if today else timezone.localdate()

    candidates = scheduled_customers(
        Customer.objects.filter(is_active=True)
    ).order_by("id")

    created_total = 0
    customers_invoiced = 0
    failed = 0
    for customer in candidates:
        if not is_billing_day(customer, day):
            continue
        try:
            created = run_invoice_run_for_customer(
                customer, year=day.year, month=day.month
            )
        except Exception:  # noqa: BLE001 — one customer must not stop the run.
            failed += 1
            logger.exception(
                "Sprint 182 §1: invoice run failed for customer %s", customer.pk
            )
            continue
        if created:
            customers_invoiced += 1
            created_total += len(created)

    return {
        "date": day.isoformat(),
        "customers_invoiced": customers_invoiced,
        "invoices_created": created_total,
        "failed": failed,
    }
