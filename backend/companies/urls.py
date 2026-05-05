from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CompanyViewSet
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
] + router.urls
