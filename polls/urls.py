"""
URL routes for the polls app.

Uses DRF Router to generate all CRUD + custom action URLs.
Included under /api/v1/polls/ by config/urls.py.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import PollViewSet

app_name = "polls"

router = DefaultRouter()
router.register("", PollViewSet, basename="poll")

urlpatterns = [
    path("", include(router.urls)),
]