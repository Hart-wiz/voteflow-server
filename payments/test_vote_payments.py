import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.db import IntegrityError, transaction

from accounts.models import User
from config.errors import ExternalServiceError
from payments.models import Payment, Transaction, Wallet
from payments.retries import retry_on_failure
from payments.services import initialize_vote_payment, process_vote_payment_webhook
from polls.models import Contest, Contestant, Poll
from voting.models import AuditLog, VoteAttempt, VotingPolicy
from voting.services import initiate_vote_attempt


class RetryDecoratorTests(TestCase):
    @patch("payments.retries.time.sleep")
    def test_retries_transient_errors_with_exponential_delays(self, sleep):
        import requests

        operation = Mock(side_effect=[requests.ConnectionError("temporary"), requests.Timeout("temporary"), "ok"])
        wrapped = retry_on_failure(max_attempts=3, delay=0.5, backoff=2)(operation)
        self.assertEqual(wrapped(), "ok")
        self.assertEqual(operation.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    @patch("payments.retries.time.sleep")
    def test_final_transient_error_becomes_external_service_error(self, sleep):
        import requests

        operation = Mock(side_effect=requests.Timeout("offline"))
        wrapped = retry_on_failure(max_attempts=3, delay=0, backoff=2)(operation)
        with self.assertRaises(ExternalServiceError):
            wrapped()
        self.assertEqual(operation.call_count, 3)


class VotePaymentTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.voter = User.objects.create_user(
            email="voter@example.com", name="Voter", password="StrongPassword123!"
        )
        self.poll = Poll.objects.create(creator=self.organizer, title="Paid Poll", slug="paid-poll")
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            source_poll=self.poll,
            title="Paid Contest",
            slug="paid-contest",
            state=Contest.State.LIVE,
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="Candidate")
        self.policy = VotingPolicy.objects.create(
            contest=self.contest,
            price_per_vote=Decimal("4.25"),
            revenue_share_percentage=80,
        )
        self.attempt = initiate_vote_attempt(self.voter, self.contest, self.contestant, 3)

    @override_settings(PAYSTACK_SECRET_KEY="sk_test")
    @patch("payments.services.requests.post")
    def test_payment_initialization_prices_attempt_and_sets_state(self, post):
        response = Mock()
        response.json.return_value = {
            "data": {"authorization_url": "https://checkout.example.test", "access_code": "access"}
        }
        post.return_value = response
        payment, url = initialize_vote_payment(self.attempt)
        self.attempt.refresh_from_db()
        self.assertEqual(url, "https://checkout.example.test")
        self.assertEqual(payment.total_amount, Decimal("12.75"))
        self.assertEqual(payment.organizer_earnings, Decimal("10.20"))
        self.assertEqual(payment.currency, "NGN")
        self.assertEqual(payment.vote_attempt_id, self.attempt.pk)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(self.attempt.state, VoteAttempt.State.PAYMENT_PENDING)
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 1275)

    def _make_pending_payment(self, reference="pay-ref-1"):
        return Payment.objects.create(
            user=self.voter,
            vote_attempt=self.attempt,
            provider_reference=reference,
            reference=reference,
            total_amount=Decimal("12.75"),
            amount=Decimal("12.75"),
            organizer_earnings=Decimal("10.20"),
            currency="NGN",
            status=Payment.Status.PENDING,
        )

    def test_provider_reference_is_unique(self):
        Payment.objects.create(provider_reference="duplicate-reference")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(provider_reference="duplicate-reference")

    def test_webhook_confirms_payment_and_credits_wallet_once(self):
        payment = self._make_pending_payment()
        self.attempt.state = VoteAttempt.State.PAYMENT_PENDING
        self.attempt.save(update_fields=["state"])
        payload = {"reference": payment.provider_reference, "amount": 1275, "currency": "NGN"}
        self.assertEqual(process_vote_payment_webhook("charge.success", payload), "confirmed")
        self.assertEqual(process_vote_payment_webhook("charge.success", payload), "duplicate")
        payment.refresh_from_db()
        self.attempt.refresh_from_db()
        wallet = Wallet.objects.get(user=self.organizer)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(self.attempt.state, VoteAttempt.State.PAYMENT_CONFIRMED)
        self.assertEqual(wallet.balance, Decimal("10.20"))
        self.assertEqual(Transaction.objects.filter(user=self.organizer, type=Transaction.Type.EARNING).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action_type=AuditLog.ActionType.PAYMENT_CONFIRMED).exists())

    def test_webhook_rejects_amount_or_currency_mismatch(self):
        payment = self._make_pending_payment("bad-payment")
        self.attempt.state = VoteAttempt.State.PAYMENT_PENDING
        self.attempt.save(update_fields=["state"])
        self.assertEqual(
            process_vote_payment_webhook(
                "charge.success",
                {"reference": payment.provider_reference, "amount": 1274, "currency": "NGN"},
            ),
            "invalid",
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(Wallet.objects.get(user=self.organizer).balance, Decimal("0.00"))

    @override_settings(PAYSTACK_SECRET_KEY="secret")
    def test_signed_webhook_endpoint_returns_202(self):
        from django.test import Client

        payment = self._make_pending_payment("http-ref")
        self.attempt.state = VoteAttempt.State.PAYMENT_PENDING
        self.attempt.save(update_fields=["state"])
        body = json.dumps(
            {"event": "charge.success", "data": {"reference": "http-ref", "amount": 1275, "currency": "NGN"}}
        ).encode()
        signature = hmac.new(b"secret", body, hashlib.sha512).hexdigest()
        response = Client().post(
            "/api/v1/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 202)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
