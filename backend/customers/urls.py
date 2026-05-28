from django.urls import path
from rest_framework.routers import DefaultRouter

from extra_work.views_pricing import (
    CustomerServicePriceDetailView,
    CustomerServicePriceListCreateView,
)

from .views import CustomerViewSet
from .views_contacts import (
    CustomerContactDetailView,
    CustomerContactListCreateView,
)
from .views_memberships import (
    CustomerBuildingDeleteView,
    CustomerBuildingListCreateView,
    CustomerCompanyPolicyView,
    CustomerUserAccessDeleteView,
    CustomerUserAccessListCreateView,
    CustomerUserDeleteView,
    CustomerUserListCreateView,
)


router = DefaultRouter()
router.register(r"", CustomerViewSet, basename="customer")


urlpatterns = [
    path(
        "<int:customer_id>/users/",
        CustomerUserListCreateView.as_view(),
        name="customer-users",
    ),
    path(
        "<int:customer_id>/users/<int:user_id>/",
        CustomerUserDeleteView.as_view(),
        name="customer-user-delete",
    ),
    # Sprint 14 — customer ↔ buildings (M:N).
    path(
        "<int:customer_id>/buildings/",
        CustomerBuildingListCreateView.as_view(),
        name="customer-buildings",
    ),
    path(
        "<int:customer_id>/buildings/<int:building_id>/",
        CustomerBuildingDeleteView.as_view(),
        name="customer-building-delete",
    ),
    # Sprint 14 — per-customer-user building access.
    path(
        "<int:customer_id>/users/<int:user_id>/access/",
        CustomerUserAccessListCreateView.as_view(),
        name="customer-user-access",
    ),
    path(
        "<int:customer_id>/users/<int:user_id>/access/<int:building_id>/",
        CustomerUserAccessDeleteView.as_view(),
        name="customer-user-access-delete",
    ),
    # Sprint 27E — per-customer CustomerCompanyPolicy read/write.
    path(
        "<int:customer_id>/policy/",
        CustomerCompanyPolicyView.as_view(),
        name="customer-policy",
    ),
    # Sprint 28 Batch 4 — per-customer Contact phone-book CRUD.
    path(
        "<int:customer_id>/contacts/",
        CustomerContactListCreateView.as_view(),
        name="customer-contacts",
    ),
    path(
        "<int:customer_id>/contacts/<int:contact_id>/",
        CustomerContactDetailView.as_view(),
        name="customer-contact-detail",
    ),
    # Sprint 28 Batch 5 — per-customer service contract prices.
    # View classes live in extra_work/views_pricing.py (the model
    # app owns the views); the URL anchor is here so the path is
    # customer-scoped and the IsSuperAdminOrCompanyAdminForCompany
    # gate resolves on the Customer object.
    path(
        "<int:customer_id>/pricing/",
        CustomerServicePriceListCreateView.as_view(),
        name="customer-pricing-list",
    ),
    path(
        "<int:customer_id>/pricing/<int:price_id>/",
        CustomerServicePriceDetailView.as_view(),
        name="customer-pricing-detail",
    ),
] + router.urls
