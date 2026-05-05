from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from accounts.views_users import UserViewSet


users_router = DefaultRouter()
users_router.register(r"users", UserViewSet, basename="user")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/companies/", include("companies.urls")),
    path("api/buildings/", include("buildings.urls")),
    path("api/customers/", include("customers.urls")),
    path("api/tickets/", include("tickets.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/", include(users_router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
