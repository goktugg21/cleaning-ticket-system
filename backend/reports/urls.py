from django.urls import path

from .views import (
    AgeBucketsView,
    ManagerThroughputView,
    StatusDistributionView,
    TicketsOverTimeView,
)


urlpatterns = [
    path(
        "status-distribution/",
        StatusDistributionView.as_view(),
        name="reports-status-distribution",
    ),
    path(
        "tickets-over-time/",
        TicketsOverTimeView.as_view(),
        name="reports-tickets-over-time",
    ),
    path(
        "manager-throughput/",
        ManagerThroughputView.as_view(),
        name="reports-manager-throughput",
    ),
    path(
        "age-buckets/",
        AgeBucketsView.as_view(),
        name="reports-age-buckets",
    ),
]
