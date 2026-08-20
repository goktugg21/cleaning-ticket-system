from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ExtraWorkCategoryOptionsView,
    ExtraWorkPricingLineItemDetailView,
    ExtraWorkPricingLineItemListCreateView,
    ExtraWorkRequestViewSet,
)
from .views_messages import (
    ExtraWorkMessageListCreateView,
    ExtraWorkMessageRecipientsView,
)
from .views_proposals import (
    ProposalDetailView,
    ProposalDirectPublishView,
    ProposalLineDetailView,
    ProposalLineListCreateView,
    ProposalLinePreviewView,
    ProposalListCreateView,
    ProposalPdfView,
    ProposalStatusHistoryView,
    ProposalTimelineView,
    ProposalTransitionView,
)


router = DefaultRouter()
router.register(r"", ExtraWorkRequestViewSet, basename="extra-work")


from .views_assignments import (
    ExtraWorkAssignableUsersView,
    ExtraWorkAssignmentListView,
    ExtraWorkBulkAssignView,
)
from .views_dates import ExtraWorkBulkDatesView
from .views_financials import ExtraWorkFinancialSummaryView
from .views_groups import (
    ExtraWorkBatchCreateView,
    ExtraWorkGroupDetailView,
    ExtraWorkGroupMembersView,
)
from .views_planning import ExtraWorkBulkPlanView

urlpatterns = [
    # Sprint 143 §6 — MUST precede the router: the DefaultRouter is
    # registered at the empty prefix, so its detail route would otherwise
    # swallow this path as a lookup value.
    path(
        "category-options/",
        ExtraWorkCategoryOptionsView.as_view(),
        name="extra-work-category-options",
    ),
    # Sprint 157 §2 — MUST precede the router for the same reason
    # `category-options/` does: the router is registered at the empty
    # prefix and its detail route would swallow "bulk-assign" as a pk.
    path(
        "bulk-assign/",
        ExtraWorkBulkAssignView.as_view(),
        name="extra-work-bulk-assign",
    ),
    # Sprint 176 §3 — same ordering rule: "bulk-dates" would be read as a
    # pk by the router's detail route if it came after.
    path(
        "bulk-dates/",
        ExtraWorkBulkDatesView.as_view(),
        name="extra-work-bulk-dates",
    ),
    # W2-D — plan many works at once. Same ordering rule as the three
    # above: the router owns the empty prefix, so its detail route would
    # read "bulk-plan" as a pk.
    path(
        "bulk-plan/",
        ExtraWorkBulkPlanView.as_view(),
        name="extra-work-bulk-plan",
    ),
    # W5-B — day-by-day creation and the group read/edit. Same ordering
    # rule as every sibling above: the router owns the empty prefix, so
    # its detail route would read "batch" and "groups" as a pk.
    path(
        "batch/",
        ExtraWorkBatchCreateView.as_view(),
        name="extra-work-batch",
    ),
    path(
        "groups/<int:pk>/",
        ExtraWorkGroupDetailView.as_view(),
        name="extra-work-group-detail",
    ),
    path(
        "groups/<int:pk>/members/",
        ExtraWorkGroupMembersView.as_view(),
        name="extra-work-group-members",
    ),
    # W1-C — the money strip's aggregate. MUST precede the router for the
    # same reason the three above do: the router owns the empty prefix,
    # so its detail route would read "financial-summary" as a pk.
    path(
        "financial-summary/",
        ExtraWorkFinancialSummaryView.as_view(),
        name="extra-work-financial-summary",
    ),
    path("", include(router.urls)),
    path(
        "<int:pk>/assignments/",
        ExtraWorkAssignmentListView.as_view(),
        name="extra-work-assignments",
    ),
    path(
        "<int:pk>/assignments/candidates/",
        ExtraWorkAssignableUsersView.as_view(),
        name="extra-work-assignment-candidates",
    ),
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
    # Sprint 13B — compute-only line preview (persists nothing).
    path(
        "<int:ew_id>/proposals/<int:pid>/lines/preview/",
        ProposalLinePreviewView.as_view(),
        name="extra-work-proposal-line-preview",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/lines/<int:lid>/",
        ProposalLineDetailView.as_view(),
        name="extra-work-proposal-line-detail",
    ),
    path(
        "<int:ew_id>/proposals/<int:pid>/pdf/",
        ProposalPdfView.as_view(),
        name="extra-work-proposal-pdf",
    ),
    # Provider override path — skip the customer-approval step on a
    # DRAFT proposal. Atomic DRAFT -> SENT -> CUSTOMER_APPROVED in
    # one request. Existing `transition/` endpoint is unchanged.
    path(
        "<int:ew_id>/proposals/<int:pid>/direct-publish/",
        ProposalDirectPublishView.as_view(),
        name="extra-work-proposal-direct-publish",
    ),
    # M1 B6 — Extra Work message thread.
    path(
        "<int:ew_id>/messages/",
        ExtraWorkMessageListCreateView.as_view(),
        name="extra-work-message-list",
    ),
    path(
        "<int:ew_id>/message-recipients/",
        ExtraWorkMessageRecipientsView.as_view(),
        name="extra-work-message-recipients",
    ),
]
