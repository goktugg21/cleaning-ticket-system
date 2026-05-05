from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet
from .views_memberships import BuildingManagerDeleteView, BuildingManagerListCreateView


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
] + router.urls
