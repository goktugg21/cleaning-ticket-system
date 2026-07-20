"""
Invoicing — Phase 2b gapless invoice numbering.

`allocate_invoice_number` is the single number allocator. Gaplessness comes
from a DEDICATED per-(company, year) counter row (`InvoiceNumberSequence`)
locked with select_for_update, mirroring the tickets state_machine locking
pattern. There is always exactly ONE row to lock per sequence, so there is
no empty-set / phantom-row race.

MUST run inside a transaction — the caller (issue_invoice / reverse_invoice
in state_machine.py) wraps this in its own @transaction.atomic block so the
allocated number and the status flip commit together (or roll back together).
"""
from __future__ import annotations

from .models import InvoiceNumberSequence


def allocate_invoice_number(company_id, year):
    """
    Allocate the next gapless invoice number for (company, year).

    Returns (number_str, seq_int), e.g. ("2026-0001", 1). Zero-padded to 4
    digits; overflows past 9999 naturally widen (e.g. "2026-10000").

    Concurrency-safe: get_or_create the (company, year) row first, then
    re-fetch it with select_for_update so two concurrent allocations serialize
    on the row lock (the second blocks until the first commits, then reads the
    incremented value) — never a duplicate, never a gap.
    """
    # Ensure the counter row exists. get_or_create is itself atomic and
    # tolerates the first-allocation race (loser catches IntegrityError and
    # re-gets).
    InvoiceNumberSequence.objects.get_or_create(
        company_id=company_id, year=year
    )
    # Row-lock it for the increment; concurrent allocators serialize here.
    seq = InvoiceNumberSequence.objects.select_for_update().get(
        company_id=company_id, year=year
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"{year}-{seq.last_number:04d}", seq.last_number
