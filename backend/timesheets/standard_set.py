"""
Sprint 152 — the standard hour-type set.
Sprint 152.1 — in the operator's own language.

A new provider company starts with an EMPTY hour-type catalog, because
the names and weights are a company's own payroll convention and
guessing them silently would be worse than an empty list. The
"Add standard set" action is the middle ground: the six kinds nearly
every cleaning operation uses, created on request, editable afterwards
like any other row.

The multipliers are the common Dutch defaults, NOT a legal authority —
an operator who pays 1.35 for overtime edits the row. The set is
deliberately not a migration or a signal on company creation: it must be
an act the operator chose, visible in the AuditLog with their name on it.

## Why the SET is translated but `HourType.name` is not

`name` is ONE data column typed by an admin, not four language columns.
That decision stands: an hour type is a company's own payroll vocabulary,
and a translatable name would imply the platform owns the term when it
does not. What Sprint 152.1 changes is only which names the BUTTON
creates — an English-profile operator seeding a fresh catalog should not
have to rename six Dutch rows first.

## The cross-language idempotency rule

`STANDARD_SLOTS` pairs the two names for each slot, and the skip test
matches a slot when EITHER name already exists. Without that pairing, a
company seeded in Dutch would gain six ENGLISH duplicates the moment
somebody with an English profile pressed the button — six rows meaning
the same thing, none of them caught by the per-company uniqueness
constraint (which compares "Overwerk" against "Overtime" and correctly
finds no collision).

So the invariant is: pressing the button twice, in either language, in
any order, creates nothing the second time.
"""
from __future__ import annotations

from decimal import Decimal


# (nl_name, en_name, multiplier, sort_order). The PAIR is the unit, not
# the name: see the cross-language idempotency rule above.
STANDARD_SLOTS = (
    ("Normale uren", "Normal hours", Decimal("1.00"), 10),
    ("Overwerk", "Overtime", Decimal("1.50"), 20),
    ("Weekenduren", "Weekend hours", Decimal("1.50"), 30),
    ("Feestdag", "Public holiday", Decimal("2.00"), 40),
    ("Ziekteverlof", "Sick leave", Decimal("1.00"), 50),
    ("Vakantie", "Vacation", Decimal("1.00"), 60),
)


def standard_hour_types(language: str | None):
    """The `(name, multiplier, sort_order)` triples to create, in the
    operator's language.

    Anything that is not exactly `"en"` falls back to Dutch — nl is the
    project's primary language (CLAUDE.md), and a user whose `language`
    is unset, or set to some future third value, gets the deployment's
    default rather than an error.
    """
    use_english = (language or "").lower() == "en"
    return tuple(
        (en_name if use_english else nl_name, multiplier, sort_order)
        for nl_name, en_name, multiplier, sort_order in STANDARD_SLOTS
    )


def slot_aliases():
    """Every name that identifies a slot, normalised for comparison.

    One frozenset per slot, in `STANDARD_SLOTS` order. The
    normalisation — strip then lowercase — is the SAME comparison
    `uniq_hour_type_name_per_company_ci` performs
    (`Lower(Trim("name"))`), so the skip test and the DB constraint
    cannot disagree about whether two names are "the same".
    """
    return tuple(
        frozenset({nl_name.strip().lower(), en_name.strip().lower()})
        for nl_name, en_name, _multiplier, _sort_order in STANDARD_SLOTS
    )
