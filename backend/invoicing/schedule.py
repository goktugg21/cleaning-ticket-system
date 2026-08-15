"""
Sprint 182 §1 — whose billing day is today.

`Customer.invoice_day_of_month` / `invoice_day_rule` used to be, in the
field's own words, informational: they "drive the who's-due list, gate
nothing". Nothing scheduled on them — verified before this sprint, and
true. §1 turns them into the trigger for the daily run, so the question
"is this customer due today?" now decides whether money moves.

That makes it exactly the wrong thing to answer in two places. The `/due/`
panel already had the computation inline; the job would have been a second
copy, and the two would eventually disagree about who got invoiced —
visible to the operator as "the panel said they were due and no invoice
appeared". So it lives here and both call it.

The two questions are close but NOT the same, and the difference is
deliberate:

  * `billing_day_reached` — "has this customer's billing day arrived at
    some point in this month?" A specific day D is reached from D onward;
    FIRST_OF_MONTH is reached all month. That is what the PANEL wants: a
    customer due on the 5th should still show as due on the 12th if
    nobody has invoiced them yet.

  * `is_billing_day` — "is today exactly this customer's billing day?"
    That is what the JOB wants. A run triggered by "reached" would fire
    again every remaining day of the month; the claim makes the repeat
    harmless, but a job that legitimately does nothing on 26 days out of
    28 is a job nobody can read the logs of.
"""
from __future__ import annotations

import calendar

from customers.models import Customer


def effective_billing_day(customer, *, year: int, month: int) -> int | None:
    """The day-of-month this customer bills on, or None if unscheduled.

    Precedence mirrors the model's own documentation:
      * `invoice_day_of_month` (1..28) when set — capped at 28 so it
        exists in every month;
      * else FIRST_OF_MONTH -> 1, LAST_OF_MONTH -> the real last day of
        THIS month (28/29/30/31, resolved against the calendar rather
        than assumed);
      * else None — no schedule set, so the customer is never due.
    """
    day = customer.invoice_day_of_month
    if day is not None:
        return day
    rule = customer.invoice_day_rule
    if rule == Customer.InvoiceDayRule.FIRST_OF_MONTH:
        return 1
    if rule == Customer.InvoiceDayRule.LAST_OF_MONTH:
        return calendar.monthrange(year, month)[1]
    return None


def is_billing_day(customer, today) -> bool:
    """Is `today` EXACTLY this customer's billing day?

    The daily job's trigger. False for an unscheduled customer — a
    customer with no billing day set is never automatically invoiced,
    which is the safe reading: nobody told us when to bill them.
    """
    day = effective_billing_day(customer, year=today.year, month=today.month)
    return day is not None and today.day == day


def billing_day_reached(customer, today) -> bool:
    """Has this customer's billing day arrived at some point this month?

    The `/due/` panel's softer test — see the module docstring for why
    the panel and the job ask different questions.

    LAST_OF_MONTH stays exact (`today.day == last_day`) rather than
    "from the last day onward", because there is no onward: the last day
    is the end of the month. That is the pre-existing behaviour and this
    extraction does not change it.
    """
    day = customer.invoice_day_of_month
    if day is not None:
        # A specific day is reached from D onward, mirroring
        # FIRST_OF_MONTH's reached-for-the-rest-of-the-month semantics.
        return today.day >= day
    rule = customer.invoice_day_rule
    if rule == Customer.InvoiceDayRule.FIRST_OF_MONTH:
        return True
    if rule == Customer.InvoiceDayRule.LAST_OF_MONTH:
        return today.day == calendar.monthrange(today.year, today.month)[1]
    return False


def scheduled_customers(queryset):
    """Narrow a Customer queryset to those with a billing schedule set.

    A customer is scheduled if it has a specific billing day OR a
    first/last rule — either establishes a due day. Shared so the panel
    and the job cannot disagree about who is even a candidate.
    """
    from django.db.models import Q

    return queryset.filter(
        Q(invoice_day_of_month__isnull=False) | ~Q(invoice_day_rule="")
    )
