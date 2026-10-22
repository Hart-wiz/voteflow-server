"""Request throttling and consistent Django-level error responses."""

import hashlib
import logging
import time
from datetime import datetime, timezone
from email.utils import format_datetime

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404, JsonResponse
from ninja_jwt.tokens import AccessToken

from .errors import VoteFlowError

logger = logging.getLogger(__name__)


def _client_identity(request):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return f"user:{user.pk}"
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            token = AccessToken(auth.split(None, 1)[1])
            return f"user:{token.get('user_id', 'unknown')}"
        except Exception:
            pass
    address = request.META.get("REMOTE_ADDR", "unknown")
    return f"ip:{address}"


class RateLimitMiddleware:
    """Apply shared-cache limits to authentication and voting API requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith("/api/v1/auth/") or path.startswith("/api/auth/"):
            limit, bucket_name = 20, "auth"
        elif (
            path.startswith("/api/v1/votes/")
            or path.startswith("/api/votes/")
            or (path.startswith("/api/v1/polls/") and path.rstrip("/").endswith("/vote"))
        ):
            limit, bucket_name = 100, "votes"
        else:
            return self.get_response(request)

        minute = int(time.time() // 60)
        identity = hashlib.sha256(_client_identity(request).encode()).hexdigest()
        key = f"voteflow:rate:{bucket_name}:{identity}:{minute}"
        try:
            if not cache.add(key, 1, timeout=70):
                count = cache.incr(key)
            else:
                count = 1
        except Exception:
            logger.exception("Rate-limit cache is unavailable")
            if not settings.DEBUG:
                return JsonResponse(
                    {
                        "error": "Rate limiting is temporarily unavailable.",
                        "code": "EXT_001",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    status=503,
                )
            return self.get_response(request)

        if count > limit:
            response = JsonResponse(
                {
                    "error": "Too many requests. Please try again later.",
                    "code": "RATE_001",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                status=429,
            )
            response["Retry-After"] = str(60 - int(time.time() % 60))
            return response
        return self.get_response(request)


class ErrorHandlingMiddleware:
    """Map Django exceptions to stable JSON for non-Ninja endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, VoteFlowError):
            status, code, message = exception.status_code, exception.code, str(exception)
        elif isinstance(exception, PermissionDenied):
            status, code, message = 403, "AUTHZ_001", str(exception) or "You do not have permission to perform this action."
        elif isinstance(exception, ValidationError):
            status, code, message = 400, "VAL_001", "The request is invalid."
        elif isinstance(exception, Http404):
            status, code, message = 404, "RES_001", str(exception) or "The requested resource was not found."
        elif isinstance(exception, IntegrityError):
            status, code, message = 400, "VAL_008", "The request conflicts with existing data."
        else:
            logger.error(
                "Unhandled request error",
                exc_info=(type(exception), exception, exception.__traceback__),
            )
            status, code, message = 500, "EXT_003", "An unexpected server error occurred."
        return JsonResponse(
            {
                "error": message,
                "code": code,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            status=status,
        )


class LegacyPollDeprecationMiddleware:
    """Announce the dated removal of the legacy Poll API surface."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path_info.startswith(("/api/v1/polls", "/api/polls")):
            sunset = getattr(settings, "API_SUNSET_AT", datetime(2026, 11, 22, tzinfo=timezone.utc))
            response["Deprecation"] = "true"
            response["Sunset"] = format_datetime(sunset.astimezone(timezone.utc), usegmt=True)
            response["Warning"] = '299 VoteFlow "The Poll API is deprecated; migrate to /api/v1/contests."'
            response["Link"] = '</api/v1/contests/>; rel="successor-version"'
        return response
