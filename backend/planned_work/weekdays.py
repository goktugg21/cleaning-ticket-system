"""ISO weekday helpers for the recurring day-model (pure, no DB access).

A WEEKLY / BIWEEKLY `RecurringJob` runs on a chosen SET of weekdays. The
set is stored on the job as a sorted, comma-separated string of ISO
weekday integers (Monday=1 .. Sunday=7) — e.g. "1,4" for Monday+Thursday.
A CSV CharField is used (not a Postgres ArrayField, which is not used
anywhere else in this codebase, nor a child table, which would spam the
membership audit on every weekday toggle): the job is already audited in
the generic full-CRUD trio, so the CSV diffs cleanly as a single
before/after string.

These helpers are the single normalize / parse contract shared by the
recurrence engine, the generator, and the serializers. Keeping them in a
DB-free module avoids an import cycle (recurrence.py imports models for
the `Frequency` enum; models.py imports these helpers for a convenience
property).
"""
from __future__ import annotations

from typing import Iterable, List

# ISO weekday numbering: Monday=1 .. Sunday=7 (matches date.isoweekday()).
WEEKDAY_MIN = 1
WEEKDAY_MAX = 7
VALID_WEEKDAYS = frozenset(range(WEEKDAY_MIN, WEEKDAY_MAX + 1))


def parse_weekdays(raw: str) -> List[int]:
    """Parse the stored CSV (e.g. "1,4") into a sorted, de-duplicated list
    of valid ISO weekday ints. Tolerant of blanks / stray whitespace /
    junk so a hand-edited value can never crash the engine."""
    if not raw:
        return []
    out = set()
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except (TypeError, ValueError):
            continue
        if n in VALID_WEEKDAYS:
            out.add(n)
    return sorted(out)


def serialize_weekdays(values: Iterable[int]) -> str:
    """Normalize an iterable of ISO weekday ints into the stored CSV form
    (sorted, de-duplicated, only valid weekdays). Invalid entries are
    dropped silently — the serializer validates the wire input before
    calling this, so this is the storage-normalization belt-and-braces."""
    clean = set()
    for v in values or []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n in VALID_WEEKDAYS:
            clean.add(n)
    return ",".join(str(v) for v in sorted(clean))
