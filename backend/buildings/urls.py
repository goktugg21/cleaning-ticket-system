from rest_framework.routers import DefaultRouter

from .views import BuildingViewSet


router = DefaultRouter()
router.register(r"", BuildingViewSet, basename="building")

urlpatterns = router.urls
