"""
Diff and value-serialization helpers for audit logging.

`compute_create_changes(instance)` and `compute_update_changes(old, new)`
both emit a {field: {"before": <v>, "after": <v>}} dict suitable for
direct storage in AuditLog.changes (a JSONField).

`compute_delete_changes(instance)` emits a snapshot keyed the same way
with after=None.

Sensitive-field redaction:
- Any concrete field whose name (case-insensitive) contains any of
  the SENSITIVE_FIELD_TOKENS substrings is dropped entirely.
- The `password` AbstractUser field is included in that filter, so
  no hashed password ever enters the audit log.

Value serialization:
- datetime / date / time -> ISO 8601 string.
- UUID -> str(uuid).
- ForeignKey -> the related pk (already what model_to_dict returns).
- Decimal -> str() (avoids float precision drift).
- TextChoices / Enum -> the underlying primitive (.value).
- bytes / memoryview / file-like values -> dropped (not auditable).
"""
from __future__ import annotations

import datetime
import decimal
import enum
import uuid
from typing import Any, Dict


# Substrings that, when present in a field's name (case-insensitive),
# cause the field to be redacted from the audit log entirely. The
# AbstractUser password column matches "password"; OAuth/JWT/PAT
# columns match "token"; OTP/MFA columns match "secret"/"otp"/"mfa";
# precomputed digests match "hash".
SENSITIVE_FIELD_TOKENS = ("password", "token", "secret", "hash", "otp", "mfa")

# Auto-managed timestamps that change on every save. They would create
# UPDATE rows that say "the row was updated", which is already implied
# by the AuditLog row itself. Drop them to keep the diff focused on
# operator-visible changes.
NOISY_FIELDS = frozenset({"updated_at", "created_at", "last_login"})


def _is_sensitive(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(token in lowered for token in SENSITIVE_FIELD_TOKENS)


def _is_auditable(field) -> bool:
    """Return True iff this concrete model field should be tracked."""
    # Skip relations to other rows (we don't audit ManyToMany / reverse FK
    # cascades). ForeignKey is fine — its column name is `<name>_id` and
    # the value is the pk.
    if field.many_to_many or field.one_to_many or field.one_to_one:
        return False
    if not getattr(field, "concrete", False):
        return False
    name = field.name
    if name in NOISY_FIELDS:
        return False
    if _is_sensitive(name):
        return False
    # The FK attribute name (e.g. "company") is a concrete field whose
    # column is "company_id". Use the column name in `_serialize_value`
    # to read the pk directly, but key the diff on the field.name so
    # readers see "company": {"before": 1, "after": 2} instead of
    # "company_id": ...
    return True


def serialize_value(value: Any) -> Any:
    """Coerce a model attribute value into a JSON-serializable scalar."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (bytes, memoryview)):
        return None
    # Lists/dicts that came out of JSONField stay as-is iff their
    # leaves are already JSON-safe. We do not attempt to deep-clean
    # arbitrary nested values; the diff engine only sees primitives
    # off concrete fields, so this branch is a defensive no-op.
    if isinstance(value, (list, dict)):
        return value
    # Last resort: stringify. This catches Choices subclasses on Django
    # < 5 where TextChoices values are already strings, and any custom
    # object with __str__.
    return str(value)


def _read_field(instance, field) -> Any:
    # ForeignKey: read the *_id attribute directly to avoid a DB hit and
    # to put the pk (an int) in the diff, not a model repr.
    if field.is_relation and field.many_to_one:
        return getattr(instance, field.attname, None)
    return getattr(instance, field.name, None)


def _snapshot(instance) -> Dict[str, Any]:
    """Return {field_name: serialized_value} for all auditable fields."""
    out: Dict[str, Any] = {}
    for field in instance._meta.get_fields():
        if not _is_auditable(field):
            continue
        out[field.name] = serialize_value(_read_field(instance, field))
    return out


def compute_create_changes(instance) -> Dict[str, Dict[str, Any]]:
    snap = _snapshot(instance)
    return {name: {"before": None, "after": value} for name, value in snap.items()}


def compute_delete_changes(instance) -> Dict[str, Dict[str, Any]]:
    snap = _snapshot(instance)
    return {name: {"before": value, "after": None} for name, value in snap.items()}


def compute_update_changes(old_snapshot: Dict[str, Any], instance) -> Dict[str, Dict[str, Any]]:
    """
    Diff an `old_snapshot` (already-serialized dict captured by pre_save)
    against a fresh snapshot of the post-save instance. Emits only the
    fields whose serialized value actually changed.
    """
    new_snapshot = _snapshot(instance)
    diff: Dict[str, Dict[str, Any]] = {}
    for name, after in new_snapshot.items():
        before = old_snapshot.get(name)
        if before != after:
            diff[name] = {"before": before, "after": after}
    return diff


def snapshot_for_pre_save(instance) -> Dict[str, Any]:
    """Public alias used by signal handlers."""
    return _snapshot(instance)
