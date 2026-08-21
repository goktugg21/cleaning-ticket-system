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

CONCURRENCY (Sprint 183 §5 — re-examined, still deferred, and here is
the code that settles where it belongs)
--------------------------------------------------------------------
Two workers firing the same beat tick would both read the unbilled pool
before either claims. `select_for_update` would close it, and the rows
that need locking are `ExtraWorkRequest` rows selected inside
`invoicing/selectors.py::_scoped_unbilled_ew_with_tickets`:

    qs = scope_extra_work_for(actor).filter(...)   # <- these rows

`selectors.py` IS this agent's file, so a `.select_for_update()` could
be added here without touching another app. It is still NOT done, for a
reason that is about correctness rather than ownership:

  * the queryset is built by `extra_work.scoping.scope_extra_work_for`
    and this module does not control its joins. `SELECT ... FOR UPDATE`
    against a query containing an outer join raises in Postgres, and the
    scoping helper's shape is free to change in an app this sprint does
    not own. A lock that works today and starts raising when another
    team adds a `select_related` is worse than no lock, because it
    fails on the nightly run at month end.
  * closing it properly means `select_for_update(of=("self",))` plus a
    guarantee about that queryset's shape — i.e. a change agreed with
    whoever owns `extra_work`, not one made unilaterally from here.

The exposure meanwhile is unchanged and small: beat delivers one tick to
one worker, so the real race is a manual Generate pressed while the
nightly run is mid-flight, which surfaces immediately as two drafts an
operator can delete. Named, located, and left — not silently accepted.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# Sprint 183 §3 — a real member of `NotificationEventType` now.
#
# Sprint 182 wrote this as a bare string because that agent did not own
# `notifications/models.py`. The rows persisted and the mails sent, but
# the value sat outside the enum so any label lookup rendered the raw
# string. The module-level alias is kept so existing importers still work.
INVOICE_RUN_EVENT = "INVOICE_RUN_COMPLETED"


def _scope_actor(company_id):
    """A provider operator whose SCOPE this run reads through.

    Sprint 183 §3 — this is NOT the author. It used to be both, and that
    conflation is what put a person's name on invoices nobody created.
    They are different questions:

      * "whose data may this read?" — needs a real user, because the read
        path goes through `extra_work.scoping.scope_extra_work_for`,
        which takes a user and lives in an app this sprint does not own.
      * "who created this invoice?" — nobody. `Invoice.created_by` is
        nullable as of migration 0007 and the run passes `system=True`,
        so its drafts render as System.

    Picks the company's longest-standing active COMPANY_ADMIN, falling
    back to any active SUPER_ADMIN. Because this only decides what the
    run may SEE — and it is immediately narrowed to the one (company,
    customer) pair the loop already chose — which of several admins it
    picks cannot change the result.

    Returns None when the company has no operator at all; the caller
    skips that customer rather than reading through nobody's scope.
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

    actor = actor or _scope_actor(customer.company_id)
    if actor is None:
        logger.warning(
            "Sprint 183 §3: no provider operator for company %s; skipping "
            "customer %s. The run needs somebody's SCOPE to read the "
            "unbilled pool through, even though the invoices it creates "
            "are attributed to the system.",
            customer.company_id,
            customer.pk,
        )
        return []

    # `system=True` — the invoices this run creates have no human author.
    # `actor` above supplies the read scope only.
    #
    # Sprint 184 §1 — `through=True`: this billing period OR ANY EARLIER
    # one. The run used to ask for work billable in the CURRENT month,
    # matched exactly, while the work it exists to bill is last month's.
    # On the 1st that question has no answer — nothing has finished in a
    # month that started hours ago — so the run created nothing, and the
    # month it skipped was never revisited, because it fires once a
    # month. A customer billing on the 15th caught the 1st-15th and
    # permanently missed the 16th-31st. The log read
    # `invoices_created: 0`, which reads as "nothing outstanding".
    #
    # "This or earlier" rather than "the previous period" is the
    # deliberate choice, for three reasons. A run missed for any reason
    # (a beat tick, a deploy, a customer whose schedule was set later)
    # is picked up by the NEXT one instead of being lost — and a lost
    # run is precisely the failure being fixed here. It makes this job
    # agree with the /due/ panel and the preview, so what an operator is
    # shown as outstanding is what the run will bill. And it matches the
    # owner's own description of the job: a draft invoice out of the
    # completed extra works, not out of one particular month's.
    #
    # Nothing can be billed twice: the CLAIM (`is_invoiced` plus the
    # live `InvoiceLine.extra_work` link) is what prevents that, not the
    # month window, so a row already invoiced is out of the pool
    # whatever period is asked for.
    created = generate_draft_invoices(
        actor,
        customer.company_id,
        customer.id,
        year,
        month,
        system=True,
        through=True,
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

    # W11 — THE RECURRING FEE, on the same run.
    #
    # A contract is the standing agreement: so many square metres, so
    # many hours a year, for so much a month. Its generator has existed
    # and been tested since Sprint 164 but nothing ever called it outside
    # a management command somebody had to type, so every contract read
    # EUR 0.00 on the billing tab and the module looked broken rather
    # than unwired. This is that wire.
    #
    # The SAME run, deliberately, not a second one: one schedule, one
    # place to look when a month is wrong. It runs after the Extra Work
    # loop because the two are independent -- contract periods are driven
    # by the contract's own billing period and first invoice date, Extra
    # Work by the customer's billing day -- and a failure in one must not
    # cost the other its run.
    #
    # `system=True` rather than an actor: `Invoice.created_by` has been
    # nullable since Sprint 183 §3 exactly so a scheduled run stops
    # putting a person's name on documents nobody created, and the Extra
    # Work half above already does this. Contract drafts now render as
    # System beside them.
    #
    # Double-creation is refused by the database, not by this function:
    # `ContractInvoice` carries UniqueConstraint(contract, period_start),
    # and the generator treats the IntegrityError as "another run has
    # this period". That is the same data-is-the-key argument the Extra
    # Work claim makes above.
    contracts_created = 0
    try:
        from contracts.invoice_generation import generate_invoices

        contracts_created = len(
            generate_invoices(system=True, on=day).created
        )
    except Exception:  # noqa: BLE001 — contracts must not cost EW its run.
        failed += 1
        logger.exception("W11: contract invoice generation failed")

    return {
        "date": day.isoformat(),
        "customers_invoiced": customers_invoiced,
        "invoices_created": created_total,
        "contract_invoices_created": contracts_created,
        "failed": failed,
    }
