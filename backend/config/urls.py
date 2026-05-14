from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views_staff import (
    BuildingStaffVisibilityDetailView,
    BuildingStaffVisibilityListCreateView,
    StaffProfileView,
)
from accounts.views_users import UserViewSet
from config.health import liveness, readiness
from tickets.urls import staff_request_router


users_router = DefaultRouter()
users_router.register(r"users", UserViewSet, basename="user")


urlpatterns = [
    # Health endpoints come first so they never collide with auth/admin
    # routing. No trailing slash — orchestrators expect the literal path.
    path("health/live", liveness),
    path("health/ready", readiness),
    # Sprint 18: Django admin moved from /admin/ to /django-admin/ so the
    # React SPA owns the /admin/* prefix end-to-end (e.g. /admin/companies,
    # /admin/users, /admin/audit-logs are now served by the SPA fallback in
    # nginx). The frontend nginx.conf was updated alongside this change.
    path("django-admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/companies/", include("companies.urls")),
    path("api/buildings/", include("buildings.urls")),
    path("api/customers/", include("customers.urls")),
    path("api/tickets/", include("tickets.urls")),
    path("api/extra-work/", include("extra_work.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/", include("audit.urls")),
    path("api/", include(users_router.urls)),
    # Sprint 24A — admin endpoints for StaffProfile +
    # BuildingStaffVisibility. Hung off the existing `/api/users/`
    # prefix so they live alongside the UserViewSet detail route
    # the admin UI already calls.
    path(
        "api/users/<int:user_id>/staff-profile/",
        StaffProfileView.as_view(),
        name="user-staff-profile",
    ),
    path(
        "api/users/<int:user_id>/staff-visibility/",
        BuildingStaffVisibilityListCreateView.as_view(),
        name="user-staff-visibility",
    ),
    path(
        "api/users/<int:user_id>/staff-visibility/<int:building_id>/",
        BuildingStaffVisibilityDetailView.as_view(),
        name="user-staff-visibility-detail",
    ),
    # Sprint 23A — staff-initiated "I want to do this work" review
    # queue. The viewset returns no results for CUSTOMER_USER so
    # the resource is invisible on the customer side.
    path("api/", include(staff_request_router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
