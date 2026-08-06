"""
Sprint 152 — the standard Dutch hour-type set.

A new provider company starts with an EMPTY hour-type catalog, because
the names and weights are a company's own payroll convention and
guessing them silently would be worse than an empty list. The
"Add standard set" action is the middle ground: the six kinds nearly
every Dutch cleaning operation uses, created on request, editable
afterwards like any other row.

The multipliers here are the common Dutch defaults, NOT a legal
authority — an operator who pays 1.35 for overtime edits the row. The
set is deliberately not a migration or a signal on company creation: it
must be an act the operator chose, visible in the AuditLog with their
name on it.
"""
from __future__ import annotations

from decimal import Decimal


# (name, multiplier, sort_order). Order is the order they are created
# in, which is also the order the pickers show them in.
STANDARD_HOUR_TYPES = (
    ("Normale uren", Decimal("1.00"), 10),
    ("Overwerk", Decimal("1.50"), 20),
    ("Weekenduren", Decimal("1.50"), 30),
    ("Feestdag", Decimal("2.00"), 40),
    ("Ziekteverlof", Decimal("1.00"), 50),
    ("Vakantie", Decimal("1.00"), 60),
)
