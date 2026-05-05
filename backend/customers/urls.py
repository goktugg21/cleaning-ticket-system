from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet
from .views_memberships import CustomerUserDeleteView, CustomerUserListCreateView


router = DefaultRouter()
router.register(r"", CustomerViewSet, basename="customer")


urlpatterns = [
    path(
        "<int:customer_id>/users/",
        CustomerUserListCreateView.as_view(),
        name="customer-users",
    ),
    path(
        "<int:customer_id>/users/<int:user_id>/",
        CustomerUserDeleteView.as_view(),
        name="customer-user-delete",
    ),
] + router.urls
