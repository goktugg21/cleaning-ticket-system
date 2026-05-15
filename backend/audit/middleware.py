"""
Stores the active HTTP request in thread-local storage so audit
signal handlers can resolve the request actor / IP / request id at
write time. The request object itself is captured (not request.user),
because DRF JWT authentication runs at the view layer and request.user
is still AnonymousUser when this middleware fires.

The thread-local is always cleared in finally so a worker thread that
served a request as user A cannot leak that identity to the next
unauthenticated request it serves.
"""
from __future__ import annotations

from . import context


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        context.set_request(request)
        # Sprint 27F-B2 (G-B6): seed the per-request actor_scope from the
        # user attached to the request at middleware time. For DRF + JWT
        # this is still AnonymousUser (JWT auth runs at the view layer),
        # in which case snapshot_actor_scope returns {} and the actor
        # scope stays empty unless the view layer overrides it via
        # set_current_actor_scope(). For session-authed Django paths the
        # user is already resolved here and the snapshot fires immediately.
        # The signal handler reads `get_current_actor_scope()` at write
        # time — views that want a richer snapshot (e.g. anchored to a
        # building) call `set_current_actor_scope` after JWT auth has
        # populated request.user.
        try:
            context.set_current_actor_scope(
                context.snapshot_actor_scope(getattr(request, "user", None))
            )
        except Exception:  # pragma: no cover — defensive
            context.set_current_actor_scope({})
        try:
            return self.get_response(request)
        finally:
            context.clear_request()
