from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views_roster import ProviderEmployeesView, StaffRosterView
from accounts.views_staff import (
    BuildingStaffVisibilityDetailView,
    BuildingStaffVisibilityListCreateView,
    StaffProfileView,
)
from accounts.views_credentials import (
    UserCredentialDetailView,
    UserCredentialDownloadView,
    UserCredentialGrantDeleteView,
    UserCredentialGrantListCreateView,
    UserCredentialListCreateView,
    UserPropertyDetailView,
    UserPropertyDownloadView,
    UserPropertyGrantDeleteView,
    UserPropertyGrantListCreateView,
    UserPropertyListCreateView,
)
from accounts.views_media import UserPhotoView
from accounts.views_permission_matrix import PermissionMatrixView
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
    # M1 B1 — in-app notification / message-center feed (bell + page).
    # Recipient-scoped: every endpoint operates on request.user only.
    path("api/notifications/", include("notifications.urls")),
    # RF-1 — aggregated message inbox (tickets + Extra Work).
    path("api/inbox/", include("notifications.urls_inbox")),
    # Sprint 28 Batch 5 — provider service catalog (ServiceCategory +
    # Service CRUD). Per-customer pricing rows are under
    # /api/customers/<id>/pricing/ — see customers/urls.py.
    path("api/services/", include("extra_work.urls_catalog")),
    # Sprint 11B Batch 3 — provider-only recurring-job templates +
    # materialized planned occurrences. STAFF / CUSTOMER_USER are 403'd
    # by the viewset permission classes.
    path("api/planned-work/", include("planned_work.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/invoices/", include("invoicing.urls")),
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
    # M2 P3 — staff credentials + custom profile properties (SoT
    # Addendum A.3). Same /api/users/<user_id>/ placement as the
    # Sprint 24A staff-* admin views. The download routes are also the
    # customer-facing document URLs surfaced in the ticket payload
    # (resolver-gated; everything else is SA/PA management-only).
    path(
        "api/users/<int:user_id>/credentials/",
        UserCredentialListCreateView.as_view(),
        name="user-credentials",
    ),
    path(
        "api/users/<int:user_id>/credentials/<int:pk>/",
        UserCredentialDetailView.as_view(),
        name="user-credential-detail",
    ),
    path(
        "api/users/<int:user_id>/credentials/<int:pk>/download/",
        UserCredentialDownloadView.as_view(),
        name="user-credential-download",
    ),
    path(
        "api/users/<int:user_id>/credentials/<int:pk>/grants/",
        UserCredentialGrantListCreateView.as_view(),
        name="user-credential-grants",
    ),
    path(
        "api/users/<int:user_id>/credentials/<int:pk>/grants/<int:grant_id>/",
        UserCredentialGrantDeleteView.as_view(),
        name="user-credential-grant-detail",
    ),
    path(
        "api/users/<int:user_id>/properties/",
        UserPropertyListCreateView.as_view(),
        name="user-properties",
    ),
    path(
        "api/users/<int:user_id>/properties/<int:pk>/",
        UserPropertyDetailView.as_view(),
        name="user-property-detail",
    ),
    path(
        "api/users/<int:user_id>/properties/<int:pk>/download/",
        UserPropertyDownloadView.as_view(),
        name="user-property-download",
    ),
    # RF-1 — profile photo (GET serve / POST upload / DELETE remove).
    path(
        "api/users/<int:user_id>/photo/",
        UserPhotoView.as_view(),
        name="user-photo",
    ),
    path(
        "api/users/<int:user_id>/properties/<int:pk>/grants/",
        UserPropertyGrantListCreateView.as_view(),
        name="user-property-grants",
    ),
    path(
        "api/users/<int:user_id>/properties/<int:pk>/grants/<int:grant_id>/",
        UserPropertyGrantDeleteView.as_view(),
        name="user-property-grant-detail",
    ),
    # Sprint 13C — provider/BM-scoped STAFF roster (Employees page
    # backend). Read-only LIST; admits BUILDING_MANAGER with a
    # building-scoped queryset (unlike the SA/CA-only UserViewSet).
    # Mounted before the staff-assignment-requests router; the two
    # prefixes (`staff/` vs `staff-assignment-requests/`) do not
    # collide.
    path("api/staff/", StaffRosterView.as_view(), name="staff-roster"),
    # Employees directory — multi-role provider workforce (PA/BM/STAFF),
    # scoped per viewer. Distinct from the STAFF-only /api/staff/ roster.
    path(
        "api/employees/",
        ProviderEmployeesView.as_view(),
        name="provider-employees",
    ),
    # Sprint 14B — read-only permission-matrix contract. Additive; does
    # not disturb the existing /api/users/<id>/effective-permissions/
    # endpoint. Admits SA / CA / BM; STAFF + CUSTOMER_USER are 403'd.
    path(
        "api/permissions/matrix/",
        PermissionMatrixView.as_view(),
        name="permission-matrix",
    ),
    # Sprint 23A — staff-initiated "I want to do this work" review
    # queue. The viewset returns no results for CUSTOMER_USER so
    # the resource is invisible on the customer side.
    path("api/", include(staff_request_router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
