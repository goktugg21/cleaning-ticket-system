"""Planned-work URL routing (Sprint 11B Batch 3).

Mounted at `/api/planned-work/` in `config/urls.py`. Provider-only —
the permission classes on the viewsets 403 STAFF / CUSTOMER_USER on
every method.
"""
from rest_framework.routers import DefaultRouter

from .views import PlannedOccurrenceViewSet, RecurringJobViewSet


router = DefaultRouter()
router.register(
    r"recurring-jobs", RecurringJobViewSet, basename="recurring-job"
)
router.register(
    r"planned-occurrences",
    PlannedOccurrenceViewSet,
    basename="planned-occurrence",
)

urlpatterns = router.urls
