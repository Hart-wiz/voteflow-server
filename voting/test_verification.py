import re
import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from hypothesis import given, settings as hypothesis_settings, strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from accounts.models import User
from config.errors import RateLimitError
from polls.models import Contest
from voting.models import VoterIdentity, VoterVerification, VotingPolicy
from voting.policies import is_identity_verified
from voting.providers import (
    ConfiguredHTTPVerificationProvider,
    EmailVerificationProvider,
    check_verification_rate_limit,
    verify_voter_identity,
)


class VerificationServiceTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.voter = User.objects.create_user(
            email="voter@example.com", name="Voter", password="StrongPassword123!"
        )
        self.contest = Contest.objects.create(
            organizer=self.organizer, title="Verify", slug="verify-contest"
        )
        self.policy = VotingPolicy.objects.create(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.EMAIL,
        )

    @override_settings(RESEND_API_KEY="re_test", DEFAULT_FROM_EMAIL="VoteFlow <test@example.com>")
    @patch("voting.providers.send_transactional_email")
    def test_email_provider_sends_and_completes_one_time_code(self, send_email):
        verification = verify_voter_identity(
            self.voter,
            self.contest,
            VotingPolicy.VerificationMethod.EMAIL,
            {},
        )
        sent_text = send_email.call_args.kwargs["text"]
        code = re.search(r"(\d{6})", sent_text).group(1)
        self.assertNotIn(code, str(verification.verification_response))
        self.assertEqual(verification.status, VoterVerification.Status.PENDING)
        verified = verify_voter_identity(
            self.voter,
            self.contest,
            VotingPolicy.VerificationMethod.EMAIL,
            {"code": code},
            verification=verification,
            complete=True,
        )
        identity = VoterIdentity.objects.get(user=self.voter, contest=self.contest)
        self.assertEqual(verified.status, VoterVerification.Status.SUCCESS)
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.VERIFIED)
        self.assertTrue(is_identity_verified(self.voter, self.contest))

    @override_settings(RESEND_API_KEY="re_test", DEFAULT_FROM_EMAIL="VoteFlow <test@example.com>")
    @patch("voting.providers.send_transactional_email")
    def test_invalid_email_code_does_not_verify_identity(self, send_email):
        verification = EmailVerificationProvider().initiate_verification(self.voter, self.contest, {})
        with self.assertRaises(ValidationError):
            EmailVerificationProvider().complete_verification(verification, {"code": "000000"})
        verification.refresh_from_db()
        identity = VoterIdentity.objects.get(user=self.voter, contest=self.contest)
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.PENDING)
        self.assertEqual(verification.status, VoterVerification.Status.FAILED)

    def test_verification_code_expiry(self):
        identity = VoterIdentity.objects.create(user=self.voter, contest=self.contest)
        verification = VoterVerification.objects.create(
            voter_identity=identity,
            provider="resend",
            method=VotingPolicy.VerificationMethod.EMAIL,
            status=VoterVerification.Status.PENDING,
            verification_response={
                "code_digest": "invalid",
                "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
            },
        )
        self.assertEqual(EmailVerificationProvider().check_status(verification), VoterVerification.Status.FAILED)

    def test_sixth_verification_attempt_in_24_hours_is_rate_limited(self):
        identity = VoterIdentity.objects.create(user=self.voter, contest=self.contest)
        for _ in range(5):
            VoterVerification.objects.create(
                voter_identity=identity,
                provider="resend",
                method=VotingPolicy.VerificationMethod.EMAIL,
            )
        with self.assertRaises(RateLimitError):
            check_verification_rate_limit(identity)

    @override_settings(
        IDENTITY_PROVIDER_URL="https://identity.example.test/verify",
        IDENTITY_PROVIDER_API_KEY="secret",
    )
    @patch("voting.providers.requests.post")
    def test_configured_identity_gateway_does_not_store_submitted_identifier(self, post):
        response = Mock()
        response.json.return_value = {"verified": True, "reference": "provider-ref-1"}
        post.return_value = response
        self.policy.verification_method = VotingPolicy.VerificationMethod.NIN
        self.policy.save()
        attempt = verify_voter_identity(
            self.voter,
            self.contest,
            VotingPolicy.VerificationMethod.NIN,
            {"nin": "12345678901"},
        )
        self.assertEqual(attempt.status, VoterVerification.Status.SUCCESS)
        self.assertNotIn("12345678901", str(attempt.verification_response))
        self.assertTrue(is_identity_verified(self.voter, self.contest))

    @override_settings(IDENTITY_PROVIDER_URL="http://identity.example.test", IDENTITY_PROVIDER_API_KEY="secret")
    def test_identity_gateway_requires_https_outside_debug(self):
        with override_settings(DEBUG=False):
            self.policy.verification_method = VotingPolicy.VerificationMethod.NIN
            self.policy.save()
            with self.assertRaises(Exception):
                ConfiguredHTTPVerificationProvider(VotingPolicy.VerificationMethod.NIN).initiate_verification(
                    self.voter, self.contest, {"nin": "secret"}
                )


class VerificationRateLimitPropertyTests(HypothesisTestCase):
    @hypothesis_settings(max_examples=10, deadline=None)
    @given(attempts=st.integers(min_value=0, max_value=7))
    def test_verification_rate_limit_property(self, attempts):
        suffix = uuid.uuid4().hex
        organizer = User.objects.create_user(
            email=f"organizer-{suffix}@example.com",
            name="Organizer",
            password="StrongPassword123!",
            role=User.Role.ORGANIZER,
        )
        user = User.objects.create_user(
            email=f"attempt-{suffix}@example.com",
            name="Attempt User",
            password="StrongPassword123!",
        )
        contest = Contest.objects.create(
            organizer=organizer,
            title="Verify",
            slug=f"verify-{suffix}",
        )
        identity = VoterIdentity.objects.create(user=user, contest=contest)
        for _ in range(attempts):
            VoterVerification.objects.create(
                voter_identity=identity,
                provider="resend",
                method=VotingPolicy.VerificationMethod.EMAIL,
            )
        if attempts >= 5:
            with self.assertRaises(RateLimitError):
                check_verification_rate_limit(identity)
        else:
            self.assertTrue(check_verification_rate_limit(identity))
