from django.urls import path

from .views import MeView, ScopedTokenObtainPairView, ScopedTokenRefreshView


urlpatterns = [
    path("token/", ScopedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", ScopedTokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="auth_me"),
]
