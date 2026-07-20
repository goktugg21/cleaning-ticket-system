from django.urls import path

from .views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
    SuperAdminCompanySubscriptionDetailView,
    SuperAdminCompanySubscriptionListView,
)

# Mounted at /api/notifications/ (see config/urls.py). The literal
# "unread-count/" and "read-all/" segments are matched before the
# "<int:pk>/read/" pattern by virtue of their distinct shapes (a single
# non-integer segment vs. <int>/read/), so there is no routing collision.
urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path(
        "unread-count/",
        NotificationUnreadCountView.as_view(),
        name="notification-unread-count",
    ),
    path(
        "read-all/",
        NotificationMarkAllReadView.as_view(),
        name="notification-read-all",
    ),
    path(
        "<int:pk>/read/",
        NotificationMarkReadView.as_view(),
        name="notification-mark-read",
    ),
    # #109 Part D — SA-only per-company subscription state.
    path(
        "company-subscriptions/",
        SuperAdminCompanySubscriptionListView.as_view(),
        name="notification-company-subscriptions",
    ),
    path(
        "company-subscriptions/<int:company_id>/",
        SuperAdminCompanySubscriptionDetailView.as_view(),
        name="notification-company-subscription-detail",
    ),
]
