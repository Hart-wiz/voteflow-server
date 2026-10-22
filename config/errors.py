"""Typed application errors mapped to stable HTTP responses."""


class VoteFlowError(Exception):
    status_code = 400
    code = "VAL_001"
    error = "Request could not be completed."

    def __init__(self, message=None, *, code=None, status_code=None):
        super().__init__(message or self.error)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class AuthenticationError(VoteFlowError):
    status_code = 401
    code = "AUTH_001"
    error = "Authentication is required."


class AuthorizationError(VoteFlowError):
    status_code = 403
    code = "AUTHZ_001"
    error = "You do not have permission to perform this action."


class RequestValidationError(VoteFlowError):
    status_code = 400
    code = "VAL_001"
    error = "The request is invalid."


class RateLimitError(VoteFlowError):
    status_code = 429
    code = "RATE_001"
    error = "Too many requests. Please try again later."


class ResourceNotFoundError(VoteFlowError):
    status_code = 404
    code = "RES_001"
    error = "The requested resource was not found."


class StateConflictError(VoteFlowError):
    status_code = 409
    code = "STATE_001"
    error = "The resource changed before this operation completed."


class ExternalServiceError(VoteFlowError):
    status_code = 503
    code = "EXT_001"
    error = "A required external service is unavailable."
