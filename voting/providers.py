"""Pluggable voter identity verification providers.

Provider response values stored in ``verification_response`` are deliberately
limited to status, provider reference, and timestamps. Raw identity documents,
biometric samples, and one-time codes are never stored there.
"""

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from config.errors import ExternalServiceError, ResourceNotFoundError, RateLimitError
from notifications.email import send_transactional_email

from .models import VoterIdentity, VoterVerification, VotingPolicy
from .policies import check_composite_verification, get_voting_policy


class VerificationProvider(ABC):
    """Provider contract for initiating, polling, and completing verification."""

    method = ""
    provider_name = "base"

    @abstractmethod
    def initiate_verification(self, voter, contest, data):
        raise NotImplementedError

    @abstractmethod
    def check_status(self, verification):
        raise NotImplementedError

    @abstractmethod
    def complete_verification(self, verification, data):
        raise NotImplementedError


def check_verification_rate_limit(voter_identity):
    """Reject a sixth verification initiation in any rolling 24-hour window."""
    since = timezone.now() - timedelta(hours=24)
    attempts = VoterVerification.objects.filter(
        voter_identity=voter_identity,
        created_at__gte=since,
    ).count()
    if attempts >= 5:
        raise RateLimitError("Verification limit reached. Try again later.")
    return True


def _digest_code(code):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class EmailVerificationProvider(VerificationProvider):
    method = VotingPolicy.VerificationMethod.EMAIL
    provider_name = "resend"

    def initiate_verification(self, voter, contest, data=None):
        identity, _ = VoterIdentity.objects.get_or_create(user=voter, contest=contest)
        with transaction.atomic():
            VoterIdentity.objects.select_for_update().get(pk=identity.pk)
            check_verification_rate_limit(identity)
            code = f"{secrets.randbelow(900000) + 100000}"
            verification = VoterVerification.objects.create(
                voter_identity=identity,
                provider=self.provider_name,
                method=self.method,
                status=VoterVerification.Status.PENDING,
                verification_response={
                    "code_digest": _digest_code(code),
                    "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
                },
            )
            try:
                send_transactional_email(
                    to=voter.email,
                    subject="Verify your VoteFlow voting identity",
                    text=f"Your verification code is {code}. It expires in 10 minutes.",
                    html=f"<p>Your verification code is <strong>{code}</strong>.</p><p>It expires in 10 minutes.</p>",
                )
            except Exception as exc:
                verification.mark_completed(VoterVerification.Status.FAILED, {"reason": "delivery_failed"})
                raise ExternalServiceError("Could not send the verification code.") from exc
        identity.verification_status = VoterIdentity.VerificationStatus.PENDING
        identity.save(update_fields=["verification_status", "updated_at"])
        return verification

    def check_status(self, verification):
        response = verification.verification_response or {}
        expires_at = response.get("expires_at")
        if verification.status == VoterVerification.Status.PENDING and expires_at:
            if timezone.now() >= datetime.fromisoformat(expires_at):
                verification.mark_completed(VoterVerification.Status.FAILED, {"reason": "expired"})
        return verification.status

    def complete_verification(self, verification, data):
        invalid_code = False
        with transaction.atomic():
            verification = VoterVerification.objects.select_for_update().select_related(
                "voter_identity__contest"
            ).get(pk=verification.pk)
            self.check_status(verification)
            payload = verification.verification_response or {}
            supplied = str((data or {}).get("code", ""))
            expected = payload.get("code_digest", "")
            invalid_code = (
                verification.status != VoterVerification.Status.PENDING
                or not supplied
                or not hmac.compare_digest(expected, _digest_code(supplied))
            )
            if invalid_code:
                verification.mark_completed(
                    VoterVerification.Status.FAILED,
                    {"reason": "invalid_or_expired"},
                )
            else:
                verification.mark_completed(
                    VoterVerification.Status.SUCCESS,
                    {"verified_at": timezone.now().isoformat()},
                )
                _refresh_identity_status(verification.voter_identity)
        if invalid_code:
            raise ValidationError({"code": "The verification code is invalid or expired."})
        return verification


class ConfiguredHTTPVerificationProvider(VerificationProvider):
    """Adapter for a deployment's identity verification gateway.

    The gateway must return ``{verified: true|false, reference?: string}`` for
    synchronous checks, or ``{verified: null, reference: string}`` for pending
    checks. Raw submitted identity values are not persisted by this service.
    """

    def __init__(self, method):
        self.method = method
        self.provider_name = "identity_gateway"

    def initiate_verification(self, voter, contest, data):
        identity, _ = VoterIdentity.objects.get_or_create(user=voter, contest=contest)
        check_verification_rate_limit(identity)
        url = getattr(settings, "IDENTITY_PROVIDER_URL", "")
        api_key = getattr(settings, "IDENTITY_PROVIDER_API_KEY", "")
        if not url or not api_key:
            raise ExternalServiceError("This identity verification provider is not configured.")
        if not url.startswith("https://") and not (settings.DEBUG and url.startswith("http://localhost")):
            raise ExternalServiceError("The identity provider URL must use HTTPS.")
        values = data or {}
        if self.method == VotingPolicy.VerificationMethod.PHONE:
            secret = values.get("phone")
        elif self.method == VotingPolicy.VerificationMethod.NIN:
            secret = values.get("nin")
        elif self.method == VotingPolicy.VerificationMethod.VOTERS_CARD:
            secret = values.get("voters_card")
        else:
            secret = values.get("provider_token")
        if not secret:
            raise ValidationError({"identity": "A provider-issued identity value is required."})
        verification = VoterVerification.objects.create(
            voter_identity=identity,
            provider=self.provider_name,
            method=self.method,
            status=VoterVerification.Status.PENDING,
            verification_response={},
        )
        try:
            response = requests.post(
                url,
                json={"method": self.method, "value": secret, "reference": str(verification.pk)},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=20,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            verification.mark_completed(VoterVerification.Status.FAILED, {"reason": "provider_error"})
            raise ExternalServiceError("Identity provider request failed.") from exc
        verified = result.get("verified")
        reference = str(result.get("reference", ""))[:255]
        if verified is True:
            verification.mark_completed(VoterVerification.Status.SUCCESS, {"reference": reference})
            _refresh_identity_status(identity)
        elif verified is False:
            verification.mark_completed(VoterVerification.Status.FAILED, {"reference": reference})
        else:
            verification.verification_response = {"reference": reference}
            verification.save(update_fields=["verification_response"])
            identity.verification_status = VoterIdentity.VerificationStatus.PENDING
            identity.save(update_fields=["verification_status", "updated_at"])
        return verification

    def check_status(self, verification):
        if verification.status != VoterVerification.Status.PENDING:
            return verification.status
        reference = (verification.verification_response or {}).get("reference")
        url = getattr(settings, "IDENTITY_PROVIDER_URL", "")
        api_key = getattr(settings, "IDENTITY_PROVIDER_API_KEY", "")
        if not reference or not url or not api_key:
            return verification.status
        try:
            response = requests.get(
                url,
                params={"reference": reference, "method": verification.method},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=20,
            )
            response.raise_for_status()
            verified = response.json().get("verified")
        except (requests.RequestException, ValueError) as exc:
            raise ExternalServiceError("Identity provider status request failed.") from exc
        if verified is True:
            verification.mark_completed(VoterVerification.Status.SUCCESS, {"reference": reference})
            _refresh_identity_status(verification.voter_identity)
        elif verified is False:
            verification.mark_completed(VoterVerification.Status.FAILED, {"reference": reference})
        return verification.status

    def complete_verification(self, verification, data=None):
        if verification.status == VoterVerification.Status.SUCCESS:
            return verification
        raise ValidationError("This provider completes checks synchronously or by its configured callback.")


def get_verification_provider(method):
    if method == VotingPolicy.VerificationMethod.EMAIL:
        return EmailVerificationProvider()
    if method in {
        VotingPolicy.VerificationMethod.PHONE,
        VotingPolicy.VerificationMethod.NIN,
        VotingPolicy.VerificationMethod.VOTERS_CARD,
        VotingPolicy.VerificationMethod.FINGERPRINT,
    }:
        return ConfiguredHTTPVerificationProvider(method)
    raise ValidationError({"method": "Select one verification method."})


def _refresh_identity_status(identity):
    policy = get_voting_policy(identity.contest)
    if not policy:
        return identity
    if policy.verification_method == VotingPolicy.VerificationMethod.COMPOSITE:
        complete = check_composite_verification(identity, policy.required_verification_methods)
    elif policy.verification_method == VotingPolicy.VerificationMethod.NONE:
        complete = True
    else:
        complete = VoterVerification.objects.filter(
            voter_identity=identity,
            method=policy.verification_method,
            status=VoterVerification.Status.SUCCESS,
        ).exists()
    identity.verification_status = (
        VoterIdentity.VerificationStatus.VERIFIED
        if complete
        else VoterIdentity.VerificationStatus.PENDING
    )
    if complete and not identity.verified_at:
        identity.verified_at = timezone.now()
    identity.save(update_fields=["verification_status", "verified_at", "updated_at"])
    return identity


def verify_voter_identity(voter, contest, method, data=None, *, verification=None, complete=False):
    """Initiate or complete a configured verification for a contest voter."""
    policy = get_voting_policy(contest)
    if not policy:
        raise ValidationError("This contest has no voting policy.")
    required = (
        policy.required_verification_methods or []
        if policy.verification_method == VotingPolicy.VerificationMethod.COMPOSITE
        else [policy.verification_method]
    )
    if method not in required:
        raise ValidationError({"method": "This method is not required by the contest policy."})
    provider = get_verification_provider(method)
    if complete:
        if not verification:
            raise ResourceNotFoundError("Verification attempt not found.")
        if verification.voter_identity.user_id != voter.id or verification.voter_identity.contest_id != contest.id:
            raise ResourceNotFoundError("Verification attempt not found.")
        return provider.complete_verification(verification, data)
    return provider.initiate_verification(voter, contest, data)
