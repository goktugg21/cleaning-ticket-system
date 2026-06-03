from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet
from .views_memberships import (
    BuildingEligibleCrewView,
    BuildingManagerDeleteView,
    BuildingManagerListCreateView,
)


router = DefaultRouter()
router.register(r"", BuildingViewSet, basename="building")


urlpatterns = [
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
