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
    ServiceCategoryDetailView,
    ServiceCategoryListCreateView,
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
