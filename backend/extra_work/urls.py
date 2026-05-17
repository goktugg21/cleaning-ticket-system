from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ExtraWorkPricingLineItemDetailView,
    ExtraWorkPricingLineItemListCreateView,
    ExtraWorkRequestViewSet,
)
from .views_proposals import (
    ProposalDetailView,
    ProposalLineDetailView,
    ProposalLineListCreateView,
    ProposalListCreateView,
    ProposalStatusHistoryView,
    ProposalTimelineView,
    ProposalTransitionView,
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
    # Sprint 28 Batch 8 — proposal builder endpoints.
    path(
        "<int:ew_id>/proposals/",
        ProposalListCreateView.as_view(),
        name="extra-work-proposal-list",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/",
        ProposalDetailView.as_view(),
        name="extra-work-proposal-detail",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/transition/",
        ProposalTransitionView.as_view(),
        name="extra-work-proposal-transition",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/status-history/",
        ProposalStatusHistoryView.as_view(),
        name="extra-work-proposal-status-history",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/timeline/",
        ProposalTimelineView.as_view(),
        name="extra-work-proposal-timeline",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/lines/",
        ProposalLineListCreateView.as_view(),
        name="extra-work-proposal-line-list",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/lines/<int:lid>/",
        ProposalLineDetailView.as_view(),
        name="extra-work-proposal-line-detail",
    ),
]
