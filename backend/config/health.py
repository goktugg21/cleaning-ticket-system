"""
Health check endpoints for load balancers and uptime monitors.

Two endpoints:
- GET /health/live  — liveness probe. Returns 200 if the WSGI worker is up.
                      Does NOT check downstream dependencies; orchestrators
                      use this to decide whether to restart the container.
- GET /health/ready — readiness probe. Returns 200 only if Django can reach
                      Postgres and Redis. Returns 503 with details if any
                      check fails. Load balancers use this to decide whether
                      to send traffic.

Both endpoints are unauthenticated (no JWT, no CSRF) — they must work for
the orchestrator before any user is logged in. Failure responses report
status names only ("error" / "ok") and never echo connection strings,
hostnames, or exception text.

Note for production deployments: with DEBUG=False, Django's ALLOWED_HOSTS
gate runs before this view. A docker-compose healthcheck calling
http://localhost:8000/health/live from inside the container sends
`Host: localhost`, which security.validate_production_settings forbids.
For prod orchestration, either (a) target the public hostname listed in
DJANGO_ALLOWED_HOSTS, (b) replace the HTTP healthcheck with a Python
script that imports Django and calls the view in-process, or (c) add an
internal hostname (the container/service name) to DJANGO_ALLOWED_HOSTS.

Sprint 134 — (c) is now done unconditionally in settings.py: "backend" (the
Docker Compose service name for this container in BOTH docker-compose.yml
and docker-compose.prod.yml) is always appended to ALLOWED_HOSTS, so an
internal HTTP request addressed by that name (`Host: backend`) now passes
the gate without loosening the production validator's ban on
localhost/127.0.0.1/wildcard. The prod compose healthcheck itself still
uses a TCP socket probe, not HTTP — that is a separate, deliberate choice
left unchanged this sprint (see docs/engineering/deployment.md §4); this
fix means switching it back to HTTP is now POSSIBLE, not that it happened.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@csrf_exempt
@require_GET
def liveness(request) -> JsonResponse:
    """Cheap liveness signal — process is up and serving requests."""
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_GET
def readiness(request) -> JsonResponse:
    """Readiness signal — downstreams are reachable."""
    checks: dict[str, str] = {}
    overall_ok = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("readiness: database check failed: %s", exc)
        checks["database"] = "error"
        overall_ok = False

    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if broker_url:
        try:
            import redis

            client = redis.Redis.from_url(broker_url, socket_connect_timeout=2)
            client.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning("readiness: redis check failed: %s", exc)
            checks["redis"] = "error"
            overall_ok = False
    else:
        checks["redis"] = "not_configured"

    payload: dict[str, Any] = {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }
    status_code = 200 if overall_ok else 503
    return JsonResponse(payload, status=status_code)
