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
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/polls/", include("polls.urls")),
    path("api/v1/wallet/", include("payments.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)