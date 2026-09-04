"""P-6 V4 — mounted at /api/search/ by config.urls."""
from django.urls import path

from .views_search import GlobalSearchView

urlpatterns = [
    path("", GlobalSearchView.as_view(), name="global-search"),
]
