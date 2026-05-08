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
        try:
            return self.get_response(request)
        finally:
            context.clear_request()
