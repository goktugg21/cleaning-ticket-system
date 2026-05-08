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
