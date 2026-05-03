from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .permissions import IsAuthenticatedAndActive
from .serializers import MeSerializer


class ScopedTokenObtainPairView(TokenObtainPairView):
    throttle_scope = "auth_token"


class ScopedTokenRefreshView(TokenRefreshView):
    throttle_scope = "auth_token_refresh"


class MeView(APIView):
    permission_classes = [IsAuthenticated, IsAuthenticatedAndActive]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return Response(serializer.data)
