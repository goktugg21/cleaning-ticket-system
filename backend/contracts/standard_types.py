"""
Sprint 169 §4 — recognising a contract type as one of the standard
kinds, so it can be read in the READER's language.

This is `timesheets/standard_set.py` applied to contract types, and it
is deliberately the same shape rather than a new idea:

  * `name` stays ONE operator-typed column. A `label_nl` / `label_en`
    pair was rejected for hour types in Sprint 152.3 and the reasons
    hold here — a company that renames a type to its own wording has
    one name, not two, and nothing should have to decide which of a
    pair a hand-typed rename went into.
  * `standard_slot` is DERIVED from the name on every save, by the ONE
    function below. `ContractType.save()` calls it and so does the data
    migration, so a stored slot can never contradict the name beside
    it — not from the API, not from a management command, not from a
    shell write.
  * The API sends the stored name PLUS the slot and the client
    translates. JSON is never translated server-side.

The consequences are the ones Sprint 152.3 accepted, restated because
they are surprising until you see why:

  * Renaming a standard type to the company's own wording DETACHES it —
    the slot goes empty and the typed name shows verbatim. That is
    correct: it is no longer the standard kind, it is theirs.
  * Renaming it back, in EITHER language, re-attaches it.
  * A custom type that happens to be spelled like a standard one reads
    as the standard one. Accepted there, accepted here: the alternative
    is a hidden flag that makes two identically-named rows behave
    differently, which is worse.
"""
from __future__ import annotations


SLOT_CLEANING = "cleaning"
SLOT_EXTRA_WORK = "extra_work"
SLOT_MACHINE = "machine"
SLOT_OTHER = "other"


# (slot, nl name, en name, sort_order). The NL names are what
# `types/standard-set/` writes for a Dutch operator; both names are
# recognised on the way back in, which is what makes a rename in either
# language re-attach.
STANDARD_CONTRACT_TYPES = (
    (SLOT_CLEANING, "Schoonmaak", "Cleaning", 10),
    (SLOT_EXTRA_WORK, "Meerwerk", "Extra Works", 20),
    (SLOT_MACHINE, "Machinewerk", "Machine", 30),
    (SLOT_OTHER, "Overig", "Other", 40),
)

STANDARD_CONTRACT_TYPE_SLOTS = tuple(
    slot for slot, _nl, _en, _order in STANDARD_CONTRACT_TYPES
)

STANDARD_CONTRACT_TYPE_CHOICES = tuple(
    (slot, en) for slot, _nl, en, _order in STANDARD_CONTRACT_TYPES
)


def normalise_name(name: str | None) -> str:
    """The comparison form of a contract-type name.

    Strip then lowercase — the SAME normalisation
    `uniq_contract_type_name_per_company_ci` performs. Recognition and
    uniqueness must agree on what "the same name" means, or a row could
    be a duplicate by one rule and a different slot by the other.
    """
    return (name or "").strip().lower()


def slot_for_name(name: str | None) -> str:
    """The standard slot a name belongs to, or `""` for a custom name.

    THE single derivation, called from `ContractType.save()`.
    """
    normalised = normalise_name(name)
    if not normalised:
        return ""
    for slot, nl_name, en_name, _order in STANDARD_CONTRACT_TYPES:
        if normalised in {normalise_name(nl_name), normalise_name(en_name)}:
            return slot
    return ""


def standard_contract_types(language: str | None):
    """The `(slot, name, sort_order)` tuples to create, in the actor's
    language. Anything that is not exactly `"en"` falls back to Dutch —
    nl is the project's primary language.
    """
    use_english = (language or "").lower() == "en"
    return tuple(
        (slot, en_name if use_english else nl_name, order)
        for slot, nl_name, en_name, order in STANDARD_CONTRACT_TYPES
    )


def slot_aliases():
    """Every name that identifies a slot, normalised, one frozenset per
    entry in `STANDARD_CONTRACT_TYPES` order.

    The standard-set action's skip test uses this so that a Dutch-seeded
    company pressing the button under an English profile is told
    "already there" rather than handed four English duplicates — the
    per-company uniqueness constraint would not object, because
    "Meerwerk" and "Extra Works" genuinely are different strings.
    """
    return tuple(
        frozenset({normalise_name(nl_name), normalise_name(en_name)})
        for _slot, nl_name, en_name, _order in STANDARD_CONTRACT_TYPES
    )
