"""Sprint W4-Q §2 — per-company warning thresholds.

WHAT WAS MISSING
----------------
Sprint W1-B shipped the three time-driven warnings and put every
threshold behind an environment variable (`SLA_WARN_*` in
`config/settings.py`). That made them tunable by a deploy, which is not
the same as tunable. Worse, one env var is ONE number for the whole
platform, and this is a multi-tenant system: a provider running a
same-day emergency service and a provider running a monthly contract
round do not agree on when silence becomes a problem, and a shared
number is wrong for both.

So the thresholds are per company, and this is the row that holds them.

NULL MEANS "NOT CONFIGURED", NOT ZERO
-------------------------------------
Every field is nullable and every NULL falls back to the settings value
INDEPENDENTLY. That is the whole migration story for existing
deployments: no row exists for any company, so every company resolves to
exactly the env var it resolved to before, and the sweep behaves byte for
byte as it did. The env var stops being the source of truth and becomes
the fallback the moment a company saves its first number — and only for
the fields that company actually filled in.

Zero is NOT a synonym for NULL here. `manager_review_business_hours = 0`
is a legal, meaningful configuration ("warn me the moment it lands in
review"), and it must never render or behave like "unset". The same rule
the money code lives by, applied to a clock.

BUSINESS HOURS, NOT SECONDS
---------------------------
The settings are seconds because they were written for the engine. A
human tuning a threshold thinks in hours of a working day, so the stored
unit is business HOURS and `sla.thresholds` does the one multiplication.
"24" on the screen means twenty-four business hours — Mon-Fri
09:00-17:00 by `SLA_BUSINESS_HOURS_*` — which is three working days, not
one calendar day, and the screen says so.

The two approval-cutoff figures are the exception and are CALENDAR days,
because a billing date is a calendar date; that asymmetry is real and is
labelled on the screen rather than smoothed over.

TENANCY
-------
One row per provider company, `OneToOneField`. A company's numbers are
read only when the subject of a warning belongs to that company (see
`sla.thresholds.ThresholdResolver`), so tuning one tenant's clock can
never move another tenant's.
"""
from django.conf import settings
from django.db import models


class SlaWarningThreshold(models.Model):
    """The per-company override set for `sla.warnings`. See module docstring."""

    company = models.OneToOneField(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="sla_warning_threshold",
    )

    #: Calendar days before the customer's billing cutoff at which the
    #: "your approval is due" warning starts. Calendar, not business —
    #: a billing date is a date on a calendar.
    approval_cutoff_days = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    #: ...and the calendar-day window inside which the one hop to the
    #: provider side also fires.
    approval_cutoff_escalate_days = models.PositiveSmallIntegerField(
        null=True, blank=True
    )

    #: Business hours a ticket may sit at WAITING_MANAGER_REVIEW before
    #: the responsible manager is warned.
    manager_review_business_hours = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    #: ...and the larger figure at which the one hop reaches the company
    #: admins.
    manager_review_escalate_business_hours = models.PositiveSmallIntegerField(
        null=True, blank=True
    )

    #: Business hours past a planned start before "this has not started"
    #: is worth saying.
    not_started_business_hours = models.PositiveSmallIntegerField(
        null=True, blank=True
    )
    #: ...and the hop to the responsible manager.
    not_started_escalate_business_hours = models.PositiveSmallIntegerField(
        null=True, blank=True
    )

    #: How long one (event type, subject, recipient) stays quiet after a
    #: warning went out, on BOTH channels. Hours on the wall clock, not
    #: business hours: a warning that is quiet for "24 business hours"
    #: would speak again on Saturday morning.
    cooldown_hours = models.PositiveSmallIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "SLA warning threshold"
        verbose_name_plural = "SLA warning thresholds"

    def __str__(self):
        return f"SLA warning thresholds for company {self.company_id}"
