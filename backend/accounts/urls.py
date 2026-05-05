from django.urls import path

from .views import (
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ScopedTokenObtainPairView,
    ScopedTokenRefreshView,
)
from .views_invitations import (
    InvitationAcceptView,
    InvitationListCreateView,
    InvitationPreviewView,
    InvitationRevokeView,
)


urlpatterns = [
    path("token/", ScopedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", ScopedTokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="auth_logout"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("me/", MeView.as_view(), name="auth_me"),
    path("invitations/", InvitationListCreateView.as_view(), name="invitation_list_create"),
    path("invitations/preview/", InvitationPreviewView.as_view(), name="invitation_preview"),
    path("invitations/accept/", InvitationAcceptView.as_view(), name="invitation_accept"),
    path("invitations/<int:pk>/revoke/", InvitationRevokeView.as_view(), name="invitation_revoke"),
]
