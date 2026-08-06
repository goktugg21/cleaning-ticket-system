"""
Sprint 152 — the standard hour-type set.
Sprint 152.1 — created in the operator's language.
Sprint 152.2 — no change.
Sprint 152.3 — and now READ in the reader's language, via recognition.

A new provider company starts with an EMPTY hour-type catalog, because
the names and weights are a company's own payroll convention and
guessing them silently would be worse than an empty list. The
"Add standard set" action is the middle ground: the six kinds nearly
every cleaning operation uses, created on request, editable afterwards
like any other row.

The multipliers are the common Dutch defaults, NOT a legal authority —
an operator who pays 1.35 for overtime edits the row.

## Why `name` is NOT multilingual columns

The obvious shape — `name_nl` / `name_en` / `name_tr` / `name_bg` — was
considered and REJECTED. An hour type is a company's own payroll
vocabulary and MOST rows are custom; a custom type has no translation
anybody can supply, so those columns would be empty for exactly the rows
that make up the bulk of a real catalog, and the UI would need the
fallback-to-`name` path anyway. `name` stays ONE operator-typed column.

## Recognition instead

`STANDARD_SLOTS` already paired each slot's Dutch and English name for
Sprint 152.1's cross-language idempotency. Sprint 152.3 makes that
pairing do double duty as a RECOGNISER: `slot_for_name()` maps any of
the twelve known spellings back to a slot key, and `HourType.save()`
stores the result in `standard_slot`. A row whose name is recognised
renders in the reader's language; a custom row renders its stored name
verbatim.

The slot is DERIVED, never latched, and the consequences are intended:

  * renaming a standard row to something of the company's own DETACHES
    it — it becomes custom and keeps the typed name verbatim;
  * renaming it back, in EITHER language, RE-ATTACHES it. Symmetric,
    precisely because nothing was latched;
  * a custom type someone happens to name "Vakantie" WILL read as
    "Vacation" in English. Accepted: it is the same word for the same
    concept, and the alternative — a stored flag set once at creation —
    drifts from the name it claims to describe the moment anybody edits
    either one.
"""
from __future__ import annotations

from decimal import Decimal


# Slot keys. Stable identifiers stored in `HourType.standard_slot` and
# mirrored by the frontend's label helper, so they must not be renamed
# casually — a changed key silently detaches every row carrying it.
SLOT_NORMAL_HOURS = "normal_hours"
SLOT_OVERTIME = "overtime"
SLOT_WEEKEND = "weekend"
SLOT_PUBLIC_HOLIDAY = "public_holiday"
SLOT_SICK_LEAVE = "sick_leave"
SLOT_VACATION = "vacation"

# (slot_key, nl_name, en_name, multiplier, sort_order).
#
# The ROW is the unit, not the name. Sprint 152.1 needed the nl/en pair
# for cross-language idempotency; Sprint 152.3 needs the same pair as a
# recogniser plus a key to store. One tuple serves all three.
STANDARD_SLOTS = (
    (SLOT_NORMAL_HOURS, "Normale uren", "Normal hours", Decimal("1.00"), 10),
    (SLOT_OVERTIME, "Overwerk", "Overtime", Decimal("1.50"), 20),
    (SLOT_WEEKEND, "Weekenduren", "Weekend hours", Decimal("1.50"), 30),
    (SLOT_PUBLIC_HOLIDAY, "Feestdag", "Public holiday", Decimal("2.00"), 40),
    (SLOT_SICK_LEAVE, "Ziekteverlof", "Sick leave", Decimal("1.00"), 50),
    (SLOT_VACATION, "Vakantie", "Vacation", Decimal("1.00"), 60),
)

# `choices` for the model field. The human-readable half is the ENGLISH
# name purely as a developer-facing label (Django admin, shell repr) —
# it is never what an end user sees; the frontend owns display.
STANDARD_SLOT_CHOICES = tuple(
    (slot, en_name) for slot, _nl, en_name, _mult, _sort in STANDARD_SLOTS
)


def normalise_name(name: str | None) -> str:
    """The comparison form of an hour-type name.

    Strip then lowercase — the SAME normalisation
    `uniq_hour_type_name_per_company_ci` performs (`Lower(Trim("name"))`).
    Recognition and uniqueness must agree on what "the same name" means,
    or a row could be a duplicate by one rule and a different slot by the
    other.
    """
    return (name or "").strip().lower()


def slot_for_name(name: str | None) -> str:
    """The standard slot a name belongs to, or `""` for a custom name.

    THE single derivation. `HourType.save()` calls it on every write and
    the data migration calls the same function, so a stored
    `standard_slot` can never contradict the `name` beside it — not from
    the API, not from a management command, not from a shell write. Same
    reason `TimeEntry.save()` derives `iso_year` / `iso_week` there.
    """
    normalised = normalise_name(name)
    if not normalised:
        return ""
    for slot, nl_name, en_name, _multiplier, _sort_order in STANDARD_SLOTS:
        if normalised in {
            normalise_name(nl_name),
            normalise_name(en_name),
        }:
            return slot
    return ""


def standard_hour_types(language: str | None):
    """The `(slot, name, multiplier, sort_order)` tuples to create, in
    the operator's language.

    Anything that is not exactly `"en"` falls back to Dutch — nl is the
    project's primary language (CLAUDE.md), and a user whose `language`
    is unset, or set to some future third value, gets the deployment's
    default rather than an error.
    """
    use_english = (language or "").lower() == "en"
    return tuple(
        (slot, en_name if use_english else nl_name, multiplier, sort_order)
        for slot, nl_name, en_name, multiplier, sort_order in STANDARD_SLOTS
    )


def slot_aliases():
    """Every name that identifies a slot, normalised, one frozenset per
    slot in `STANDARD_SLOTS` order.

    Kept as the standard-set action's BACKSTOP now that `standard_slot`
    is the primary skip test: a row created before Sprint 152.3 and never
    re-saved would carry an empty slot, and the alias check still
    recognises it by name. (The data migration backfills those, so this
    is belt and braces — but the belt costs one set lookup.)
    """
    return tuple(
        frozenset({normalise_name(nl_name), normalise_name(en_name)})
        for _slot, nl_name, en_name, _multiplier, _sort_order in STANDARD_SLOTS
    )


def render_standard_label(slot: str, stored_name: str, language: str | None) -> str:
    """The display label for an hour type, SERVER-side.

    Used ONLY by the CSV export — see
    `exports.build_timesheet_summary_csv`. Every JSON payload sends the
    stored `name` plus the slot and lets the client translate; a
    downloaded file has no client, so it renders here instead.

    Falls back to the stored name for a custom type (slot `""`, or a slot
    key this build does not know), and to Dutch for an unset or unknown
    language.
    """
    if not slot:
        return stored_name
    use_english = (language or "").lower() == "en"
    for candidate, nl_name, en_name, _multiplier, _sort_order in STANDARD_SLOTS:
        if candidate == slot:
            return en_name if use_english else nl_name
    return stored_name
