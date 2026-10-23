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

from datetime import datetime, timezone

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, JsonResponse, HttpResponse
from django.urls import path
from ninja import NinjaAPI

from accounts.api import router as auth_router
from accounts.admin_api import router as admin_router
from notifications.api import router as notifications_router
from payments.api import router as payments_router
from payments.api import webhooks_router
from polls.api import router as polls_router
from polls.contest_api import router as contests_router
from voting.api import router as voting_router, verification_router
from config.errors import VoteFlowError

# from polls.
api = NinjaAPI(title="VoteFlow API", version="1.0.0", urls_namespace="api-v1")
spec_api = NinjaAPI(title="VoteFlow API", version="1.0.0", urls_namespace="api")


def _error_response(request, exception, *, status=None, code=None, message=None):
    details = None
    if isinstance(exception, ValidationError):
        details = exception.message_dict if hasattr(exception, "message_dict") else exception.messages
        default_message = "The request is invalid."
        status, code = status or 400, code or "VAL_001"
    elif isinstance(exception, PermissionDenied):
        default_message = str(exception) or "You do not have permission to perform this action."
        status, code = status or 403, code or "AUTHZ_001"
    elif isinstance(exception, IntegrityError):
        default_message = "The request conflicts with existing data."
        status, code = status or 400, code or "VAL_008"
    elif isinstance(exception, Http404):
        default_message = "The requested resource was not found."
        status, code = status or 404, code or "RES_001"
    elif isinstance(exception, VoteFlowError):
        default_message = str(exception)
        status, code = status or exception.status_code, code or exception.code
    else:
        default_message = str(exception) or "An unexpected server error occurred."
        status, code = status or 500, code or "EXT_003"
    body = {
        "error": message or default_message,
        "code": code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if details is not None:
        body["details"] = details
    return JsonResponse(body, status=status)


for _error_type in (VoteFlowError, ValidationError, PermissionDenied, IntegrityError, Http404):
    api.add_exception_handler(
        _error_type,
        lambda request, exc: _error_response(request, exc),
    )

for _api in (api, spec_api):
    _api.add_router("/auth/", auth_router)
    _api.add_router("/polls/", polls_router)
    _api.add_router("/wallet/", payments_router)
    _api.add_router("/notifications/", notifications_router)
    _api.add_router("/contests/", contests_router)
    _api.add_router("/votes/", voting_router)
    _api.add_router("/verification/", verification_router)
    _api.add_router("/admin/", admin_router)
    _api.add_router("/webhooks/", webhooks_router)


# api.add_router("/polls/")
api_v1_patterns = [
    path("admin/", admin.site.urls),
    path("", api.urls),  # Django Ninja endpoints & docs sit perfectly here
]

urlpatterns = [
    path("health/", lambda request: HttpResponse("ok")),
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    # Spec routes use /api/...; retain /api/v1/... for the shipped client.
    path("api/", spec_api.urls),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
