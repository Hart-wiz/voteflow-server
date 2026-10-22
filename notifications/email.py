"""Small Resend-backed email adapter used by account and notification flows."""

import logging

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)
RESEND_EMAILS_URL = "https://api.resend.com/emails"


def send_transactional_email(*, to: str, subject: str, text: str, html: str | None = None):
    """Send one email through Resend and return its response payload.

    In local DEBUG mode a missing key is logged and treated as a skipped send,
    which keeps development usable before Resend is configured. Production
    fails clearly rather than silently dropping transactional email.
    """
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        if settings.DEBUG:
            logger.info("Skipping Resend email to %s: RESEND_API_KEY is not configured", to)
            return {"skipped": True}
        raise ImproperlyConfigured("RESEND_API_KEY must be configured to send email.")

    payload = {
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    if html:
        payload["html"] = html

    try:
        response = requests.post(
            RESEND_EMAILS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        logger.exception("Resend failed to deliver email to %s", to)
        raise
