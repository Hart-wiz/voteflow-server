"""Bounded exponential retry for transient payment-provider failures."""

import logging
import time
from functools import wraps

import requests

from config.errors import ExternalServiceError

logger = logging.getLogger(__name__)


def retry_on_failure(max_attempts=3, delay=0.5, backoff=2):
    """Retry transient HTTP/provider failures with bounded exponential delay."""
    if max_attempts < 1 or delay < 0 or backoff < 1:
        raise ValueError("Invalid retry policy.")

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            wait = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return function(*args, **kwargs)
                except (requests.RequestException, ExternalServiceError) as exc:
                    if attempt == max_attempts:
                        logger.error("Payment provider call failed after %s attempts", attempt)
                        raise ExternalServiceError("Payment provider request failed.") from exc
                    logger.warning("Payment provider request failed; retry %s/%s", attempt, max_attempts)
                    time.sleep(wait)
                    wait *= backoff

        return wrapped

    return decorate
