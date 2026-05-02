from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import IsAuthenticatedAndActive
from .serializers import MeSerializer


class MeView(APIView):
    permission_classes = [IsAuthenticated, IsAuthenticatedAndActive]

    def get(self, request):
        serializer = MeSerializer(request.user)
        return Response(serializer.data)
