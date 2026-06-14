from django.urls import path
from .views import cast_vote

urlpatterns = [
    path("vote/", cast_vote),
]