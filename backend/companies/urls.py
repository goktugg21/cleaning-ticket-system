from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyViewSet
from .views_media import CompanyLogoView
from .views_memberships import CompanyAdminDeleteView, CompanyAdminListCreateView


router = DefaultRouter()
router.register(r"", CompanyViewSet, basename="company")


# Listed before router.urls so the nested admin routes take priority over the
# router's pk + action pattern when both could match a `/{id}/<word>/` URL.
urlpatterns = [
    path(
        "<int:company_id>/admins/",
        CompanyAdminListCreateView.as_view(),
        name="company-admins",
    ),
    path(
        "<int:company_id>/admins/<int:user_id>/",
        CompanyAdminDeleteView.as_view(),
        name="company-admin-delete",
    ),
    # RF-1 — company logo (GET serve / POST upload / DELETE remove).
    path(
        "<int:company_id>/logo/",
        CompanyLogoView.as_view(),
        name="company-logo",
    ),
] + router.urls
