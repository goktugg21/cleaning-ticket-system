"""
Sprint 160 — gapless contract numbering.

`allocate_contract_number` is the single number allocator for this app.
Gaplessness comes from a DEDICATED per-(company, year) counter row
(`ContractNumberSequence`) locked with `select_for_update`.

This MIRRORS THE SHAPE of `invoicing/numbering.py` and imports nothing
from it. That is deliberate: the two modules stand alone, and a
contract number is not an invoice number — sharing an allocator would
make the two sequences one, which is exactly the bug the per-entity
counter row exists to prevent.

Two differences from the invoicing allocator, both intended:

  * Contract numbers are assigned at CREATE, not at a later state
    transition. Invoice numbering moved to SEND (PR #113) because a
    number is a legal claim on a document that has left the building; a
    contract is referred to by number while it is still a draft.
  * The year is the contract's `start_date` year, not the allocation
    year. A 2027 contract drafted in December 2026 is a 2027 contract,
    and its number should say so. Gaplessness is per (company, year)
    either way.

MUST run inside a transaction — the caller (the create path in
`serializers.py`) wraps this in `transaction.atomic()` so the allocated
number and the contract row commit together, or roll back together.
"""
from __future__ import annotations

from .models import ContractNumberSequence


CONTRACT_NUMBER_PREFIX = "CNT"


def format_contract_number(year: int, seq: int) -> str:
    """Render `CNT-YYYY-NNNN`. Zero-padded to 4 digits; overflow past
    9999 naturally widens (e.g. "CNT-2026-10000") rather than wrapping.
    """
    return f"{CONTRACT_NUMBER_PREFIX}-{year}-{seq:04d}"


def allocate_contract_number(company_id, year):
    """Allocate the next gapless contract number for (company, year).

    Returns `(number_str, seq_int)`, e.g. `("CNT-2026-0001", 1)`.

    Concurrency-safe: `get_or_create` the (company, year) row first —
    itself atomic, and it tolerates the first-allocation race — then
    re-fetch it with `select_for_update` so two concurrent allocations
    serialize on the row lock. The second blocks until the first
    commits, then reads the incremented value: never a duplicate, never
    a gap.
    """
    ContractNumberSequence.objects.get_or_create(
        company_id=company_id, year=year
    )
    seq = ContractNumberSequence.objects.select_for_update().get(
        company_id=company_id, year=year
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return format_contract_number(year, seq.last_number), seq.last_number
