from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet
from .views_building_types import (
    BuildingTypeDetailView,
    BuildingTypeListCreateView,
)
from .views_bulk import (
    BuildingBulkDeactivateView,
    BuildingBulkLinkView,
    BuildingBulkUpdateView,
)
from .views_memberships import (
    BuildingEligibleCrewView,
    BuildingManagerDeleteView,
    BuildingManagerListCreateView,
)
from .views_summary import (
    BuildingContactListView,
    BuildingCustomerListView,
    BuildingStaffListView,
    BuildingSummaryView,
)


router = DefaultRouter()
router.register(r"", BuildingViewSet, basename="building")


urlpatterns = [
    # Sprint 178 §1 — the building-type catalog. ABOVE `router.urls` for
    # the same reason the bulk family is: the router owns the empty
    # prefix, so its detail route would read "types" as a pk.
    path(
        "types/",
        BuildingTypeListCreateView.as_view(),
        name="building-type-list",
    ),
    path(
        "types/<int:building_type_id>/",
        BuildingTypeDetailView.as_view(),
        name="building-type-detail",
    ),
    # Sprint 154 §I.2/§I.3/§I.4 — the bulk-write family. These MUST stay
    # above `router.urls`: the router owns the empty prefix, so its
    # detail route `^(?P<pk>[^/.]+)/$` would otherwise swallow
    # "bulk-link" as a pk.
    path(
        "bulk-link/",
        BuildingBulkLinkView.as_view(),
        name="building-bulk-link",
    ),
    path(
        "bulk-deactivate/",
        BuildingBulkDeactivateView.as_view(),
        name="building-bulk-deactivate",
    ),
    path(
        "bulk-update/",
        BuildingBulkUpdateView.as_view(),
        name="building-bulk-update",
    ),
    # Sprint 154 §I.5 — the inverse of /api/customers/<id>/buildings/.
    path(
        "<int:building_id>/customers/",
        BuildingCustomerListView.as_view(),
        name="building-customers",
    ),
    # Sprint 154 §G.2 — the per-building reads of two relations that
    # have always been editable from the OTHER end (the user's page and
    # the customer's contacts page) but were never readable from the
    # building. Writes still go through /bulk-link/.
    path(
        "<int:building_id>/staff/",
        BuildingStaffListView.as_view(),
        name="building-staff",
    ),
    path(
        "<int:building_id>/contacts/",
        BuildingContactListView.as_view(),
        name="building-contacts",
    ),
    # Sprint 154 §I.6 — the building detail dashboard read.
    path(
        "<int:building_id>/summary/",
        BuildingSummaryView.as_view(),
        name="building-summary",
    ),
    path(
        "<int:building_id>/managers/",
        BuildingManagerListCreateView.as_view(),
        name="building-managers",
    ),
    path(
        "<int:building_id>/managers/<int:user_id>/",
        BuildingManagerDeleteView.as_view(),
        name="building-manager-delete",
    ),
    # Provider-only: eligible default crew (staff + managers) for a
    # building, for the planned-work recurring-job form (pre-ticket).
    path(
        "<int:building_id>/eligible-crew/",
        BuildingEligibleCrewView.as_view(),
        name="building-eligible-crew",
    ),
] + router.urls
