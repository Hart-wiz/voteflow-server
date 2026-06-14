from django.urls import path
from .views import poll_list, poll_detail, poll_results

urlpatterns = [
    path("", poll_list),
    path("<slug:slug>/", poll_detail),
    path("<slug:slug>/results/", poll_results),
]