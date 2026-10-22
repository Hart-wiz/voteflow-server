from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from hypothesis import given, settings as hypothesis_settings, strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from accounts.models import User
from config.errors import StateConflictError
from notifications.models import Notification
from payments.models import Payment, Wallet
from polls.models import Contest, Contestant, Poll
from voting.models import AuditLog, Vote, VoteAttempt, VotingPolicy
from voting.services import (
    VOTE_ATTEMPT_TRANSITIONS,
    commit_vote,
    expire_vote_attempts,
    initiate_vote_attempt,
    is_vote_attempt_transition_allowed,
    payment_status_is_confirmed,
    progress_vote_attempt,
)


class VoteWorkflowTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            email="organizer@example.com", name="Organizer", password="StrongPassword123!", role=User.Role.ORGANIZER
        )
        self.voter = User.objects.create_user(
            email="voter@example.com", name="Voter", password="StrongPassword123!"
        )
        self.poll = Poll.objects.create(creator=self.organizer, title="Voting", slug="voting")
        self.contest = Contest.objects.create(
            organizer=self.organizer,
            source_poll=self.poll,
            title="Voting Contest",
            slug="voting-contest",
            state=Contest.State.LIVE,
            end_time=timezone.now() + timedelta(days=1),
        )
        self.contestant = Contestant.objects.create(poll=self.poll, name="Candidate")
        self.policy = VotingPolicy.objects.create(contest=self.contest)

    def _attempt(self, quantity=1):
        return initiate_vote_attempt(self.voter, self.contest, self.contestant, quantity)

    def test_vote_initiation_requires_live_contest(self):
        for state in Contest.State.values:
            Contest.objects.filter(pk=self.contest.pk).update(state=state)
            if state == Contest.State.LIVE:
                self.assertEqual(self._attempt().state, VoteAttempt.State.VERIFIED)
            else:
                with self.assertRaises(ValidationError):
                    self._attempt()

    def test_paid_contest_requires_verified_payment_before_commit(self):
        self.policy.price_per_vote = Decimal("2.50")
        self.policy.save()
        attempt = self._attempt(2)
        payment = Payment.objects.create(
            user=self.voter,
            vote_attempt=attempt,
            provider_reference="pending-ref",
            total_amount=Decimal("5.00"),
            organizer_earnings=Decimal("4.00"),
            currency="NGN",
        )
        progress_vote_attempt(attempt, VoteAttempt.State.PAYMENT_PENDING)
        with self.assertRaises(ValidationError):
            commit_vote(attempt, payment)
        payment.status = Payment.Status.CONFIRMED
        payment.save(update_fields=["status"])
        progress_vote_attempt(attempt, VoteAttempt.State.PAYMENT_CONFIRMED)
        rows = commit_vote(attempt, payment)
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.vote_number for row in rows], [1, 2])

    def test_vote_count_and_quantity_record_accuracy(self):
        attempt = self._attempt(4)
        rows = commit_vote(attempt)
        self.contestant.refresh_from_db()
        self.assertEqual(len(rows), 4)
        self.assertEqual(sum(row.vote_quantity for row in rows), 4)
        self.assertEqual(self.contestant.votes, 4)
        self.assertEqual(Vote.objects.filter(poll=self.poll).count(), 4)

    def test_verification_policy_blocks_unverified_voter(self):
        self.policy.verification_method = VotingPolicy.VerificationMethod.EMAIL
        self.policy.save()
        attempt = self._attempt()
        self.assertEqual(attempt.state, VoteAttempt.State.IDENTITY_CHECK)
        with self.assertRaises(ValidationError):
            commit_vote(attempt)

    def test_attempt_state_machine_rejects_invalid_transition(self):
        attempt = self._attempt()
        self.assertIn(VoteAttempt.State.PAYMENT_PENDING, VOTE_ATTEMPT_TRANSITIONS[VoteAttempt.State.VERIFIED])
        with self.assertRaises(ValidationError):
            progress_vote_attempt(attempt, VoteAttempt.State.EXPIRED)

    def test_attempt_state_machine_accepts_valid_progression(self):
        attempt = self._attempt()
        attempt = progress_vote_attempt(attempt, VoteAttempt.State.PAYMENT_PENDING)
        attempt = progress_vote_attempt(attempt, VoteAttempt.State.PAYMENT_CONFIRMED)
        self.assertEqual(attempt.state, VoteAttempt.State.PAYMENT_CONFIRMED)

    def test_vote_context_is_limited_to_100_kb(self):
        attempt = self._attempt()
        with self.assertRaises(ValidationError):
            progress_vote_attempt(attempt, VoteAttempt.State.PAYMENT_PENDING, context={"payload": "x" * 110_000})

    def test_attempts_older_than_30_minutes_expire(self):
        attempt = self._attempt()
        attempt.state = VoteAttempt.State.PAYMENT_PENDING
        attempt.created_at = timezone.now() - timedelta(minutes=31)
        attempt.save(update_fields=["state", "created_at"])
        self.assertEqual(expire_vote_attempts(), 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.EXPIRED)

    def test_vote_commit_writes_notification_and_audit_log(self):
        attempt = self._attempt()
        commit_vote(attempt)
        self.assertTrue(Notification.objects.filter(receiver=self.organizer).exists())
        self.assertTrue(AuditLog.objects.filter(action_type=AuditLog.ActionType.VOTE_COMPLETED).exists())
        self.assertTrue(Wallet.objects.filter(user=self.organizer).exists())


class VoteQuantityPropertyTests(HypothesisTestCase):
    @hypothesis_settings(max_examples=5, deadline=None)
    @given(quantity=st.integers(min_value=1, max_value=8))
    def test_vote_quantity_property_creates_sequential_rows(self, quantity):
        suffix = uuid.uuid4().hex
        organizer = User.objects.create_user(
            email=f"organizer-{suffix}@example.com",
            name="Organizer",
            password="StrongPassword123!",
            role=User.Role.ORGANIZER,
        )
        voter = User.objects.create_user(
            email=f"voter-{suffix}@example.com",
            name="Voter",
            password="StrongPassword123!",
        )
        poll = Poll.objects.create(creator=organizer, title="Voting", slug=f"voting-{suffix}")
        contest = Contest.objects.create(
            organizer=organizer,
            source_poll=poll,
            title="Voting Contest",
            slug=f"voting-contest-{suffix}",
            state=Contest.State.LIVE,
            end_time=timezone.now() + timedelta(days=1),
        )
        contestant = Contestant.objects.create(poll=poll, name="Candidate")
        VotingPolicy.objects.create(contest=contest)
        attempt = initiate_vote_attempt(voter, contest, contestant, quantity)
        previous = Vote.objects.filter(poll=poll).count()
        rows = commit_vote(attempt)
        self.assertEqual(len(rows), quantity)
        self.assertEqual(
            [row.vote_number for row in rows],
            list(range(previous + 1, previous + quantity + 1)),
        )
        self.assertTrue(all(row.vote_quantity == 1 for row in rows))
        contestant.refresh_from_db()
        self.assertEqual(contestant.votes, sum(row.vote_quantity for row in rows))


class VoteAttemptStateGraphPropertyTests(SimpleTestCase):
    @hypothesis_settings(max_examples=50)
    @given(
        source=st.sampled_from(VoteAttempt.State.values),
        target=st.sampled_from(VoteAttempt.State.values),
    )
    def test_state_graph_contains_only_declared_transitions(self, source, target):
        self.assertEqual(
            is_vote_attempt_transition_allowed(source, target),
            target in VOTE_ATTEMPT_TRANSITIONS[source],
        )


class PaymentStatusPropertyTests(SimpleTestCase):
    @hypothesis_settings(max_examples=20)
    @given(status=st.sampled_from(Payment.Status.values))
    def test_only_confirmed_payments_can_back_a_vote(self, status):
        self.assertEqual(
            payment_status_is_confirmed(status),
            status == Payment.Status.CONFIRMED,
        )
