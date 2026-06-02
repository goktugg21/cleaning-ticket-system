"""
Sprint 12C — Dutch (NL) phone-number validation + normalization.

Used by the contact promote/link/invite path (``customers.promotion``):
a phone is NOT required to create/edit a plain ``Contact``, but IS
required to promote a ``Contact`` into an authenticated customer
``User``.

``phonenumbers`` is not a project dependency (and not installed in the
runtime image — verified Sprint 12C), so this is a conservative,
dependency-free validator scoped to NL numbers. If a full libphonenumber
dependency is ever adopted, swap the body of ``normalize_nl_phone`` and
keep the signature.

``normalize_nl_phone(raw)`` returns the E.164 form
(``+31XXXXXXXXX`` — the ``+31`` country code plus the 9-digit national
significant number) for a valid Dutch number, or ``None`` for anything
it cannot confidently accept.

Accepted input shapes (the separators space, ``-``, ``.``, ``(`` and
``)`` are ignored):

  * ``+31`` + 9 significant digits     e.g. ``+31 6 1234 5678``
  * ``0031`` + 9 significant digits    e.g. ``0031 20 123 4567``
  * ``0`` + 9 significant digits       e.g. ``06 12345678`` / ``020 1234567``

The 9-digit national significant number must start ``1``-``9`` (the
leading trunk ``0`` is a national prefix, never part of the significant
number), so an international prefix immediately followed by ``0``
(e.g. ``+310...``) is rejected as malformed.
"""
from __future__ import annotations

import re
from typing import Optional

# Cosmetic separators a human might type; stripped before matching.
_SEPARATORS_RE = re.compile(r"[ \t\-.()]")
# A Dutch national significant number: 9 digits, first digit non-zero.
_NL_NATIONAL_RE = re.compile(r"[1-9]\d{8}")


def normalize_nl_phone(raw: Optional[str]) -> Optional[str]:
    """Return the E.164 (`+31XXXXXXXXX`) form of a valid NL number, or
    ``None`` if ``raw`` is empty or not a number we can confidently
    accept. Pure / no side effects."""
    if raw is None:
        return None
    cleaned = _SEPARATORS_RE.sub("", str(raw).strip())
    if not cleaned:
        return None

    if cleaned.startswith("0031"):
        national = cleaned[4:]
    elif cleaned.startswith("+31"):
        national = cleaned[3:]
    elif cleaned.startswith("0"):
        national = cleaned[1:]
    else:
        return None

    if not _NL_NATIONAL_RE.fullmatch(national):
        return None
    return "+31" + national


def is_valid_nl_phone(raw: Optional[str]) -> bool:
    """True iff ``raw`` is a phone number ``normalize_nl_phone`` accepts."""
    return normalize_nl_phone(raw) is not None
