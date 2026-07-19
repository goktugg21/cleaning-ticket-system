"""RF-1 — inbox routes, mounted at /api/inbox/ (see config/urls.py).

The literal "unread-count/" and "mark-read/" segments are distinct in
shape from the bare "" list route, so there is no routing collision.
"""
from django.urls import path

from .views_inbox import (
    InboxListView,
    InboxMarkReadView,
    InboxUnreadCountView,
)

urlpatterns = [
    path("", InboxListView.as_view(), name="inbox-list"),
    path(
        "unread-count/",
        InboxUnreadCountView.as_view(),
        name="inbox-unread-count",
    ),
    path("mark-read/", InboxMarkReadView.as_view(), name="inbox-mark-read"),
]
