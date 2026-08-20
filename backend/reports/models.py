"""W4-R — the per-person hourly rate, and the reason it lives HERE.

    W3-H shipped one deployment-wide rate,
    `LABOUR_COST_HOURLY_RATE_EUR`, and called it "the one knob until a
    real per-person rate is designed". This is that design.

## Why a wage model is in `reports/` and not in `timesheets/`

`timesheets` records HOURS and WEIGHTED hours and never computes money.
That is written at the top of `timesheets/models.py`, restated at
`HourType.multiplier` ("a WEIGHT, not a rate"), and enforced by a test
that walks every non-test file in that package and fails if the string
`hourly_rate` appears in one
(`reports/tests/test_w3h_extra_work_hours.py`).

So a wage cannot live next to the hours it prices. `reports` is the app
allowed to read across modules — it is already where `labour_cost.py`
does the one multiplication in the system — and a rate is an input to
that multiplication. It lives beside it.

This is the FIRST model in the `reports` app, which until now was views
and pure functions over other apps' tables. That is a deliberate change
of shape and not an accident: the rate is not derivable from anything
else, so it has to be stored, and it may not be stored where it would
belong most naturally.

## THE DECISION THAT MATTERS: time-ranged, not snapshotted

A rate changes. When it does, work already done must keep costing what
it cost. There are two ways to get that:

  1. **Snapshot the rate onto the hour entry** at write time, the way
     `TimeEntry.multiplier_snapshot` snapshots the weight.
  2. **Version the rate itself** and resolve it as of the DATE of the
     hour being costed.

We chose 2, and the choice was not close. Option 1 requires a money
column on `TimeEntry`, which is a `timesheets` model — the one place a
rate may never appear. It would break the module's founding rule and
fail the purity test on the same commit. The seam W3-H named
(`reports.labour_cost.resolve_hourly_rate`) exists precisely so the
answer never has to reach into that app.

So: one row per (employee, company, `valid_from`). The rate in force on
a day is the row with the LATEST `valid_from` at or before that day,
ties broken by `-id` — the identical resolution shape
`extra_work.pricing.resolve_price` and `timesheets.ContractHours`
already use, so this repo has one versioning idiom rather than three.

**A raise in March writes a NEW row dated March.** January's hours
still resolve January's row, so January's cost figure is byte-identical
the day after the raise as the day before. There is a test that does
exactly that: cost the job, grant a raise, cost it again, assert
equality.

`valid_from` alone, with no `valid_to`: a closed range can leave a GAP
(a day covered by no row), and a gap would silently fall through to the
deployment rate — a different number, arrived at by nobody's decision.
An open-ended row superseded by the next one cannot produce a gap or an
overlap by construction.

## Editing history is allowed, and is not the same thing

A row can be corrected (PATCH) or removed (DELETE) by SA / CA, and both
re-price the period that row covered. That is intended. The failure
mode this model exists to prevent is a rate change SILENTLY re-pricing
the past as a side effect of an ordinary raise; an operator explicitly
editing a historical row is fixing a typo they can see, and every such
write lands on the `AuditLog` with a before/after diff.

## Zero is not a legal wage

`hourly_rate` is validated `>= 0.01`. Zero is a legal PRICE — what a
customer is charged can genuinely be nothing — but a deployment or an
operator that typed 0 into a WAGE field has typed a placeholder. The
resolver refuses it for the deployment setting for the same reason
(`labour_cost.resolve_hourly_rate`), and the two must agree.

## Who may read a rate

SUPER_ADMIN and COMPANY_ADMIN, and nobody else — not BUILDING_MANAGER,
not STAFF, not any customer-side role. Enforced at the API by
`reports.permissions.IsLabourRateManager` and by the scoped queryset in
`reports.labour_rate_scope`, never by hiding a field on a screen.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


#: The floor for a stored wage. A separate module constant so the
#: serializer can quote the SAME number in its friendly 400 instead of
#: re-typing it and drifting from the validator below.
MIN_HOURLY_RATE = Decimal("0.01")


class EmployeeHourlyRate(models.Model):
    """What one employee's hour costs the provider, from one date on.

    See the module docstring for the versioning rule, which is the whole
    point of the model. In short: never edited to change a rate, always
    superseded by a new row from a new date, and resolved as of the date
    of the hour being costed.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="employee_hourly_rates",
        help_text=(
            "Provider company this rate applies within — the tenant "
            "anchor, the same shape TimeEntry.company and "
            "ContractHours.company use. A person who works for two "
            "providers has two rates and neither can read the other."
        ),
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="hourly_rates",
        help_text=(
            "The provider-side employee this rate is for. Never a "
            "customer-side user, never a SUPER_ADMIN — a platform admin "
            "is not a provider employee and cannot have hours filed "
            "against them (timesheets.scope.PROVIDER_EMPLOYEE_ROLES)."
        ),
    )
    hourly_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(MIN_HOURLY_RATE)],
        help_text=(
            "Euros per hour of work, applied to WEIGHTED hours so an "
            "overtime hour costs what its multiplier says. Must be at "
            "least 0.01: zero is a legal price but not a legal wage."
        ),
    )
    valid_from = models.DateField(
        help_text=(
            "First day this rate is in force. Open-ended — it stays in "
            "force until a row with a later valid_from supersedes it. "
            "Hours dated BEFORE this day keep resolving the previous "
            "row, which is what stops a raise re-pricing history."
        ),
    )
    note = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Why the rate changed, in the operator's own words. Free "
            "text and optional; it is read by people, never parsed."
        ),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_employee_hourly_rates",
        help_text="Who recorded this rate. PROTECT: an author is never erased.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Newest first: the rate list is read as "what is it now, and
        # what was it before", in that order.
        ordering = ["-valid_from", "-id"]
        constraints = [
            # One rate per person per company per START DATE. Without
            # this, two rows sharing a date make "the row in force" a
            # coin flip decided by insertion order, and the same job
            # would cost two different amounts on two page loads.
            # Created WITH the table, so there is never a window in
            # which the column exists without the constraint.
            models.UniqueConstraint(
                fields=["company", "employee", "valid_from"],
                name="uniq_employee_hourly_rate_per_start_date",
            ),
        ]
        indexes = [
            # The resolution query, exactly: rows for these employees in
            # this company, ordered by valid_from. Costing a job with a
            # ten-person crew must not be ten table scans.
            models.Index(
                fields=["company", "employee", "valid_from"],
                name="rep_emp_rate_lookup_idx",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return f"{self.employee_id} @ {self.hourly_rate} from {self.valid_from}"
