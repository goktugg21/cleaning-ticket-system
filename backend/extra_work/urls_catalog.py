"""
Sprint 28 Batch 5 — URL routes for the provider service catalog.

This module is included at the top-level under `/api/services/`
(see `backend/config/urls.py`). The customer-scoped pricing routes
(`CustomerServicePrice`) live in `backend/customers/urls.py` next
to the existing Contact / membership routes — the URL anchor is a
routing detail; the model and view both live in this app.
"""
from django.urls import path

from .views_catalog import (
    ManagedUnitDetailView,
    ManagedUnitListCreateView,
    ServiceBulkRaiseView,
    ServiceCategoryArchiveActionView,
    ServiceCategoryDetailView,
    ServiceCategoryListCreateView,
    ServiceCategoryUnarchiveActionView,
    ServiceDetailView,
    ServiceListCreateView,
)


urlpatterns = [
    path(
        "categories/",
        ServiceCategoryListCreateView.as_view(),
        name="service-category-list",
    ),
    path(
        "categories/<int:category_id>/",
        ServiceCategoryDetailView.as_view(),
        name="service-category-detail",
    ),
    # Sprint 138 §2a — archive a category together with its
    # services (one transaction); unarchive restores the category
    # alone. Mounted before the bare Service routes for the same
    # reason "units/" is.
    path(
        "categories/<int:category_id>/archive/",
        ServiceCategoryArchiveActionView.as_view(),
        name="service-category-archive",
    ),
    path(
        "categories/<int:category_id>/unarchive/",
        ServiceCategoryUnarchiveActionView.as_view(),
        name="service-category-unarchive",
    ),
    path(
        "bulk-raise/",
        ServiceBulkRaiseView.as_view(),
        name="service-bulk-raise",
    ),
    # Sprint 123 — managed unit catalog. Mounted before the bare "" /
    # "<id>/" Service routes below so "units/" can never be swallowed
    # by Service's own <int:service_id> pattern (it wouldn't match a
    # non-numeric segment anyway, but the explicit ordering documents
    # the same precedent the customer `my/` routes follow elsewhere).
    path(
        "units/",
        ManagedUnitListCreateView.as_view(),
        name="managed-unit-list",
    ),
    path(
        "units/<int:unit_id>/",
        ManagedUnitDetailView.as_view(),
        name="managed-unit-detail",
    ),
    path(
        "",
        ServiceListCreateView.as_view(),
        name="service-list",
    ),
    path(
        "<int:service_id>/",
        ServiceDetailView.as_view(),
        name="service-detail",
    ),
]
