from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyBulkDeactivateView, CompanyViewSet
from .views_media import CompanyLogoView
from .views_memberships import CompanyAdminDeleteView, CompanyAdminListCreateView
from .views_summary import (
    CompanyAdminDetailListView,
    CompanyBuildingListView,
    CompanyCustomerListView,
    CompanyEmployeeListView,
    CompanySummaryView,
)


router = DefaultRouter()
router.register(r"", CompanyViewSet, basename="company")


# Listed before router.urls so the nested admin routes take priority over the
# router's pk + action pattern when both could match a `/{id}/<word>/` URL.
urlpatterns = [
    # Sprint 157 §3 — BEFORE the router, whose detail route would
    # otherwise swallow "bulk-deactivate" as a pk.
    path(
        "bulk-deactivate/",
        CompanyBulkDeactivateView.as_view(),
        name="company-bulk-deactivate",
    ),
    path(
        "<int:company_id>/admins/",
        CompanyAdminListCreateView.as_view(),
        name="company-admins",
    ),
    path(
        "<int:company_id>/admins/<int:user_id>/",
        CompanyAdminDeleteView.as_view(),
        name="company-admin-delete",
    ),
    # RF-1 — company logo (GET serve / POST upload / DELETE remove).
    path(
        "<int:company_id>/logo/",
        CompanyLogoView.as_view(),
        name="company-logo",
    ),
    # Sprint 156 §1 — the company detail page's five reads. Listed here,
    # BEFORE `router.urls`, for the same reason the admin routes above
    # are: the router's pk + action pattern would otherwise swallow a
    # `/{id}/<word>/` URL and route it to the viewset instead.
    path(
        "<int:company_id>/summary/",
        CompanySummaryView.as_view(),
        name="company-summary",
    ),
    path(
        "<int:company_id>/admins-detail/",
        CompanyAdminDetailListView.as_view(),
        name="company-admins-detail",
    ),
    path(
        "<int:company_id>/employees/",
        CompanyEmployeeListView.as_view(),
        name="company-employees",
    ),
    path(
        "<int:company_id>/buildings/",
        CompanyBuildingListView.as_view(),
        name="company-buildings",
    ),
    path(
        "<int:company_id>/customers/",
        CompanyCustomerListView.as_view(),
        name="company-customers",
    ),
] + router.urls
