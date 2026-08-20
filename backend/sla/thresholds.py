"""Sprint W4-Q §2 — resolving a company's warning thresholds.

ONE READER, ONE RULE
--------------------
Every threshold in `sla.warnings` is read through this module and
nowhere else. The rule it implements is one sentence: **the company's
own value if it set one, otherwise the settings value.** Per field, not
per row — a company that set only the manager-review clock keeps the
platform default for everything else.

`settings.SLA_WARN_*` therefore stops being the source of truth and
becomes the FALLBACK. Nothing had to be migrated for that to be true: no
company has a row until somebody saves one, and a company with no row
resolves to exactly the numbers it resolved to before this sprint.

UNITS
-----
The settings are seconds (they were written for the engine). The stored
overrides are business HOURS (they were written for a person). The
conversion happens here, once, on the way out — `resolve()` always hands
`sla.warnings` seconds, so the sweep never has to know which unit came
from where.

The two approval-cutoff figures are calendar DAYS in both places; a
billing cutoff is a date on a calendar and pretending otherwise would
make the screen lie.

ONE QUERY PER SWEEP
-------------------
`ThresholdResolver` loads every override row once and answers from a
dict. The sweep iterates tickets across many companies and a
per-subject query would turn one sweep into thousands. There are tens of
provider companies, not millions, so loading the lot is cheaper than
being clever.

TENANCY
-------
`resolve(company_id)` reads ONE company's row. There is no path here
that lets company A's number reach company B's warning: the caller
passes the subject row's own `company_id`, and an unknown or None
company id resolves to the platform defaults rather than to somebody
else's numbers.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

#: The seven knobs, in the order the screen shows them. Each entry is
#: (model field, settings name, unit). `unit` is what the STORED value
#: means, which is also what the API and the screen speak:
#:   "days"           calendar days (a billing cutoff is a calendar date)
#:   "business_hours" hours inside SLA_BUSINESS_HOURS_* on SLA_BUSINESS_DAYS
#:   "hours"          plain wall-clock hours
#:
#: Exported and iterated by the serializer, the view and the tests, so a
#: new threshold is added in ONE place. A second hand-maintained list
#: would be the `PERMISSION_GROUPS` mistake this project has already
#: made once (CLAUDE.md, frontend conventions).
THRESHOLD_FIELDS = (
    ("approval_cutoff_days", "SLA_WARN_APPROVAL_CUTOFF_DAYS", "days"),
    (
        "approval_cutoff_escalate_days",
        "SLA_WARN_APPROVAL_CUTOFF_ESCALATE_DAYS",
        "days",
    ),
    (
        "manager_review_business_hours",
        "SLA_WARN_MANAGER_REVIEW_BUSINESS_SECONDS",
        "business_hours",
    ),
    (
        "manager_review_escalate_business_hours",
        "SLA_WARN_MANAGER_REVIEW_ESCALATE_BUSINESS_SECONDS",
        "business_hours",
    ),
    (
        "not_started_business_hours",
        "SLA_WARN_NOT_STARTED_BUSINESS_SECONDS",
        "business_hours",
    ),
    (
        "not_started_escalate_business_hours",
        "SLA_WARN_NOT_STARTED_ESCALATE_BUSINESS_SECONDS",
        "business_hours",
    ),
    ("cooldown_hours", "SLA_WARN_COOLDOWN_HOURS", "hours"),
)

#: Settings fallbacks that are stored in SECONDS. Everything else in
#: `THRESHOLD_FIELDS` is already in the unit the model stores.
_SETTINGS_IN_SECONDS = frozenset(
    name for _field, name, unit in THRESHOLD_FIELDS if unit == "business_hours"
)


def default_for(field: str) -> int:
    """The platform fallback for one field, in the STORED unit."""
    for name, setting_name, unit in THRESHOLD_FIELDS:
        if name != field:
            continue
        raw = int(getattr(settings, setting_name))
        if setting_name in _SETTINGS_IN_SECONDS:
            # Seconds in settings, business hours on the model. Integer
            # division is deliberate: a fallback that is not a whole
            # number of hours cannot be represented on the screen, and
            # rounding it down warns EARLIER, never later.
            return raw // 3600
        return raw
    raise KeyError(field)


def defaults() -> dict:
    """Every platform fallback, in the stored unit. What a company with
    no row of its own is running on."""
    return {name: default_for(name) for name, _s, _u in THRESHOLD_FIELDS}


@dataclass(frozen=True)
class ResolvedThresholds:
    """One company's effective numbers, in the units the SWEEP wants.

    Days stay days; business hours become business SECONDS, because that
    is what `business_hours.business_seconds_between` returns and the
    comparison should not carry a conversion at every call site.
    """

    approval_cutoff_days: int
    approval_cutoff_escalate_days: int
    manager_review_business_seconds: int
    manager_review_escalate_business_seconds: int
    not_started_business_seconds: int
    not_started_escalate_business_seconds: int
    cooldown_hours: int


def _to_resolved(stored: dict) -> ResolvedThresholds:
    return ResolvedThresholds(
        approval_cutoff_days=stored["approval_cutoff_days"],
        approval_cutoff_escalate_days=stored["approval_cutoff_escalate_days"],
        manager_review_business_seconds=(
            stored["manager_review_business_hours"] * 3600
        ),
        manager_review_escalate_business_seconds=(
            stored["manager_review_escalate_business_hours"] * 3600
        ),
        not_started_business_seconds=(
            stored["not_started_business_hours"] * 3600
        ),
        not_started_escalate_business_seconds=(
            stored["not_started_escalate_business_hours"] * 3600
        ),
        cooldown_hours=stored["cooldown_hours"],
    )


def stored_values(company_id) -> dict:
    """One company's effective numbers in the STORED unit — what the API
    and the screen show. `None` company id yields the platform defaults."""
    from .models import SlaWarningThreshold

    base = defaults()
    if company_id is None:
        return base
    row = SlaWarningThreshold.objects.filter(company_id=company_id).first()
    return merge(row, base)


def merge(row, base=None) -> dict:
    """Overlay one override row onto the platform defaults, per field.

    `is None` and not falsiness: 0 is a legal threshold ("warn me the
    moment it lands") and must not be read as "unset". This is the same
    distinction the money rule makes between unpriced and free, and it
    is wrong in exactly the same way if it is collapsed.
    """
    values = dict(base if base is not None else defaults())
    if row is None:
        return values
    for name, _setting, _unit in THRESHOLD_FIELDS:
        override = getattr(row, name)
        if override is not None:
            values[name] = int(override)
    return values


def resolve(company_id) -> ResolvedThresholds:
    """The effective thresholds for ONE company, in sweep units."""
    return _to_resolved(stored_values(company_id))


class ThresholdResolver:
    """Per-sweep cache: one query for every override row, then a dict.

    Instantiated once per `sla.warnings.sweep` call and handed the
    subject's own `company_id` for every row it inspects. A subject whose
    company has no row gets the platform defaults; there is no code path
    on which one company's stored number can answer for another.
    """

    def __init__(self):
        from .models import SlaWarningThreshold

        self._defaults = defaults()
        self._rows = {
            row.company_id: row
            for row in SlaWarningThreshold.objects.all()
        }
        self._cache: dict = {}

    def for_company(self, company_id) -> ResolvedThresholds:
        if company_id not in self._cache:
            self._cache[company_id] = _to_resolved(
                merge(self._rows.get(company_id), self._defaults)
            )
        return self._cache[company_id]
