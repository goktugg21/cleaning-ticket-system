"""Sprint W4-Q §2 — mounted at /api/sla/ (see config/urls.py).

`sla` had no HTTP surface before this sprint: the engine is signal and
Celery driven and deliberately has no API of its own. This is a
configuration surface, not an engine surface — it reads and writes the
numbers the engine is measured against, and nothing here can move a
ticket's SLA state.
"""
from django.urls import path

from .views_thresholds import (
    SlaWarningThresholdDetailView,
    SlaWarningThresholdListView,
)

urlpatterns = [
    path(
        "warning-thresholds/",
        SlaWarningThresholdListView.as_view(),
        name="sla-warning-threshold-list",
    ),
    path(
        "warning-thresholds/<int:company_id>/",
        SlaWarningThresholdDetailView.as_view(),
        name="sla-warning-threshold-detail",
    ),
]
