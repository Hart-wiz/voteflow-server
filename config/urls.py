"""
Root URL configuration for VoteFlow.

All API endpoints are prefixed with /api/v1/ to match the frontend's
NEXT_PUBLIC_API_URL configuration.

Route map:
    /admin/                → Django admin
    /api/v1/auth/          → accounts app  (register, login, logout, me, token refresh)
    /api/v1/polls/         → polls app     (CRUD, vote, results, my-polls)
    /api/v1/wallet/        → payments app  (balance, transactions, withdraw, pay, webhook)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from accounts.api import router as auth_router
from payments.api import router as payments_router
from polls.api import router as polls_router

# from polls.
api = NinjaAPI(title="VoteFlow API", version="1.0.0", urls_namespace="api-v1")

api.add_router("/auth/", auth_router)
api.add_router("/polls/", polls_router)
api.add_router("/wallet/", payments_router)


# api.add_router("/polls/")
api_v1_patterns = [
    path("admin/", admin.site.urls),
    path("", api.urls),  # Django Ninja endpoints & docs sit perfectly here
]

urlpatterns = [
    path("api/v1/", api.urls),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
