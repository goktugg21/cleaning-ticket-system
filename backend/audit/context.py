"""
Thread-local request context for audit logging.

The middleware (audit.middleware.AuditContextMiddleware) stores the
*current request object* — not the user — for the duration of the
request. Helpers below resolve actor / IP / request id at the moment
the audit log is written. This matters for DRF + JWT: when Django
middleware fires, request.user is still AnonymousUser because JWT
authentication runs at the view layer. By the time post_save signals
fire (after serializer.save() returns inside the view), DRF has set
request.user to the authenticated user, so a *lazy* lookup yields the
real actor instead of None.

For background/Celery writes the middleware never runs and these
helpers return None / None / None — those events are recorded with
actor=None, which is the correct semantics for system writes.
"""
from __future__ import annotations

import threading
from typing import Optional


_state = threading.local()


def set_request(request) -> None:
    _state.request = request


def clear_request() -> None:
    if hasattr(_state, "request"):
        del _state.request
    # Sprint 27F-B2: also clear the per-request reason + actor scope so
    # a worker thread that served request A cannot leak its operator
    # intent / scope snapshot into request B's audit rows.
    if hasattr(_state, "reason"):
        del _state.reason
    if hasattr(_state, "actor_scope"):
        del _state.actor_scope


def _get_request():
    return getattr(_state, "request", None)


def get_current_actor():
    """Return the request.user iff authenticated; else None."""
    request = _get_request()
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        return None
    return user


def get_current_request_ip() -> Optional[str]:
    """
    Return the originating client IP. Trusts only the FIRST entry of
    X-Forwarded-For (set by an upstream proxy we control); otherwise
    falls back to REMOTE_ADDR. Returns None outside an HTTP request.
    """
    request = _get_request()
    if request is None:
        return None
    meta = getattr(request, "META", {}) or {}
    xff = meta.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return meta.get("REMOTE_ADDR") or None


def get_current_request_id() -> Optional[str]:
    """
    Return the X-Request-Id header if the upstream proxy / load
    balancer set one. We do not generate request ids ourselves in this
    sprint — the column is nullable and stays NULL when no header is
    present. Returns None outside an HTTP request.
    """
    request = _get_request()
    if request is None:
        return None
    meta = getattr(request, "META", {}) or {}
    request_id = meta.get("HTTP_X_REQUEST_ID") or meta.get("HTTP_X_CORRELATION_ID")
    if request_id:
        return str(request_id)[:128]
    return None


# ---------------------------------------------------------------------------
# Sprint 27F-B2 (closes G-B6) — `reason` + `actor_scope` thread-local helpers.
#
# `reason` is set by the calling view BEFORE the audited mutation fires, so
# the signal handler can pick it up when it writes the AuditLog row. Default
# is the empty string — legacy / unannotated writes get `reason=""`.
#
# `actor_scope` is set by the middleware (for every authenticated request,
# via `snapshot_actor_scope(request.user)`) so EVERY audit row carries a
# snapshot of what the actor could see at the moment of the write. Views
# that need to record a stronger anchor (e.g. "this write happened in the
# context of building X") may call `set_current_actor_scope` again with an
# enriched dict — the snapshot is intentionally a flat JSON-serialisable
# dict so an operator can read it without instantiating Django models.
#
# Both default to the empty value (str / dict) so signal handlers can call
# the getters unconditionally — no None to guard against on write.
# ---------------------------------------------------------------------------


def set_current_reason(reason: str) -> None:
    """Store the operator-supplied reason for the current request."""
    _state.reason = str(reason) if reason is not None else ""


def get_current_reason() -> str:
    """Return the reason set for the current request, or ''."""
    return getattr(_state, "reason", "") or ""


def set_current_actor_scope(scope: dict) -> None:
    """Store the actor-scope snapshot for the current request."""
    _state.actor_scope = scope if isinstance(scope, dict) else {}


def get_current_actor_scope() -> dict:
    """Return the actor-scope snapshot set for the current request, or {}."""
    value = getattr(_state, "actor_scope", None)
    return value if isinstance(value, dict) else {}


def snapshot_actor_scope(user) -> dict:
    """
    Build a flat, JSON-serialisable snapshot of an actor's role +
    scope anchors. Read directly from the user's memberships — does
    NOT consult the wider scope helpers (no transitive resolution),
    so the snapshot is cheap and side-effect free.

    Shape:
        {
          "role": <UserRole string>,
          "user_id": <int>,
          "company_ids": [<CompanyUserMembership.company_id>...],
          "customer_id": <int | None>,    # from CustomerUserMembership
          "building_id": None,            # caller-supplied via
                                          # set_current_actor_scope; the
                                          # snapshot defaults to None
        }

    For anonymous / unauthenticated users, returns {}.
    """
    if user is None:
        return {}
    if not getattr(user, "is_authenticated", False):
        return {}
    try:
        # Late imports so this helper does not pull membership tables
        # at module-load time (audit.context is imported very early).
        from companies.models import CompanyUserMembership
        from customers.models import CustomerUserMembership

        company_ids = list(
            CompanyUserMembership.objects.filter(user=user).values_list(
                "company_id", flat=True
            )
        )
        customer_id = (
            CustomerUserMembership.objects.filter(user=user)
            .values_list("customer_id", flat=True)
            .first()
        )
    except Exception:  # pragma: no cover — defensive
        company_ids = []
        customer_id = None

    return {
        "role": getattr(user, "role", None),
        "user_id": getattr(user, "id", None),
        "company_ids": company_ids,
        "customer_id": customer_id,
        "building_id": None,
    }
