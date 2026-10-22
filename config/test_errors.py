import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase

from config.errors import (
    AuthenticationError,
    AuthorizationError,
    ExternalServiceError,
    RateLimitError,
    RequestValidationError,
    ResourceNotFoundError,
    StateConflictError,
)
from config.middleware import ErrorHandlingMiddleware
from config.urls import _error_response


class ErrorResponseTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/api/v1/example/")

    def test_domain_errors_map_to_expected_status_and_codes(self):
        cases = (
            (AuthenticationError(), 401, "AUTH_001"),
            (AuthorizationError(), 403, "AUTHZ_001"),
            (RequestValidationError(), 400, "VAL_001"),
            (RateLimitError(), 429, "RATE_001"),
            (ResourceNotFoundError(), 404, "RES_001"),
            (StateConflictError(), 409, "STATE_001"),
            (ExternalServiceError(), 503, "EXT_001"),
        )
        for error, status, code in cases:
            response = _error_response(self.request, error)
            data = json.loads(response.content)
            self.assertEqual(response.status_code, status)
            self.assertEqual(data["code"], code)
            self.assertIn("error", data)
            self.assertIn("timestamp", data)

    def test_django_validation_and_permission_errors_are_consistent(self):
        response = _error_response(self.request, ValidationError({"name": "required"}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["code"], "VAL_001")
        denied = _error_response(self.request, PermissionDenied("denied"))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(json.loads(denied.content)["error"], "denied")

    def test_http_404_and_integrity_error_map_to_client_statuses(self):
        self.assertEqual(_error_response(self.request, Http404()).status_code, 404)
        self.assertEqual(_error_response(self.request, IntegrityError()).status_code, 400)

    def test_error_middleware_returns_consistent_json(self):
        middleware = ErrorHandlingMiddleware(lambda request: None)
        response = middleware.process_exception(self.request, StateConflictError("stale version"))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["code"], "STATE_001")
        self.assertEqual(payload["error"], "stale version")
        self.assertIn("timestamp", payload)
