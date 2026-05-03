from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import TicketAttachmentListCreateView, TicketMessageListCreateView, TicketViewSet


router = DefaultRouter()
router.register(r"", TicketViewSet, basename="ticket")

urlpatterns = [
    path(
        "<int:ticket_id>/attachments/",
        TicketAttachmentListCreateView.as_view(),
        name="ticket-attachments",
    ),
    path(
        "<int:ticket_id>/messages/",
        TicketMessageListCreateView.as_view(),
        name="ticket-messages",
    ),
] + router.urls
