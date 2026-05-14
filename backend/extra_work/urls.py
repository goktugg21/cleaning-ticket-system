from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ExtraWorkPricingLineItemDetailView,
    ExtraWorkPricingLineItemListCreateView,
    ExtraWorkRequestViewSet,
)


router = DefaultRouter()
router.register(r"", ExtraWorkRequestViewSet, basename="extra-work")


urlpatterns = [
    path("", include(router.urls)),
    path(
        "<int:ew_id>/pricing-items/",
        ExtraWorkPricingLineItemListCreateView.as_view(),
        name="extra-work-pricing-list",
    ),
    path(
        "<int:ew_id>/pricing-items/<int:lid>/",
        ExtraWorkPricingLineItemDetailView.as_view(),
        name="extra-work-pricing-detail",
    ),
]
