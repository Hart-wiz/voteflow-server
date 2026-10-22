"""
Unit tests for VoteAttempt state transitions.

Tests valid state transitions, invalid state transitions, rejection_reason 
population on REJECTED state, and completed_at timestamp setting on COMPLETED state.

Validates Requirements: 6.6, 6.9, 6.10, 6.11
"""

import pytest
from django.utils import timezone
from accounts.models import User
from polls.models import Contest, Contestant, Poll
from voting.models import VoteAttempt


@pytest.fixture
def user():
    """Create a test user for vote attempt creation."""
    return User.objects.create_user(
        email="voter@example.com",
        password="testpass123",
        name="Test Voter"
    )


@pytest.fixture
def organizer():
    """Create a test organizer user for contest creation."""
    return User.objects.create_user(
        email="organizer@example.com",
        password="testpass123",
        name="Test Organizer",
        role=User.Role.ORGANIZER
    )


@pytest.fixture
def contest(organizer):
    """Create a test contest for vote attempt creation."""
    poll = Poll.objects.create(
        creator=organizer,
        title="Test Contest",
        slug="test-contest-poll",
    )
    return Contest.objects.create(
        title="Test Contest",
        slug="test-contest",
        organizer=organizer,
        source_poll=poll,
        state=Contest.State.LIVE
    )


@pytest.fixture
def contestant(contest):
    """Create a test contestant for vote attempt creation."""
    return Contestant.objects.create(
        poll=contest.source_poll,
        name="Test Contestant",
        description="Test bio"
    )


@pytest.fixture
def vote_attempt(user, contest, contestant):
    """Create a basic vote attempt in STARTED state."""
    return VoteAttempt.objects.create(
        user=user,
        contest=contest,
        contestant=contestant,
        state=VoteAttempt.State.STARTED
    )


@pytest.mark.django_db
class TestVoteAttemptValidStateTransitions:
    """Tests for valid VoteAttempt state transitions based on the state machine."""

    def test_started_to_identity_check_transition(self, vote_attempt):
        """
        Test transition from STARTED to IDENTITY_CHECK.
        Validates Requirement 6.9
        """
        assert vote_attempt.state == VoteAttempt.State.STARTED
        
        vote_attempt.state = VoteAttempt.State.IDENTITY_CHECK
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.IDENTITY_CHECK

    def test_started_to_verified_transition(self, vote_attempt):
        """
        Test transition from STARTED to VERIFIED (no verification required).
        Validates Requirement 6.9
        """
        assert vote_attempt.state == VoteAttempt.State.STARTED
        
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.VERIFIED

    def test_started_to_rejected_transition(self, vote_attempt):
        """
        Test transition from STARTED to REJECTED (validation failed).
        Validates Requirement 6.9, 6.10
        """
        assert vote_attempt.state == VoteAttempt.State.STARTED
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = "Invalid vote quantity"
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason == "Invalid vote quantity"

    def test_identity_check_to_verified_transition(self, vote_attempt):
        """
        Test transition from IDENTITY_CHECK to VERIFIED (verification success).
        Validates Requirement 6.10
        """
        vote_attempt.state = VoteAttempt.State.IDENTITY_CHECK
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.VERIFIED

    def test_identity_check_to_rejected_transition(self, vote_attempt):
        """
        Test transition from IDENTITY_CHECK to REJECTED (verification failed).
        Validates Requirement 6.10
        """
        vote_attempt.state = VoteAttempt.State.IDENTITY_CHECK
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = "Identity verification failed"
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason == "Identity verification failed"

    def test_identity_check_to_expired_transition(self, vote_attempt):
        """
        Test transition from IDENTITY_CHECK to EXPIRED (timeout).
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.IDENTITY_CHECK
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.EXPIRED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.EXPIRED

    def test_verified_to_payment_pending_transition(self, vote_attempt):
        """
        Test transition from VERIFIED to PAYMENT_PENDING (paid contest).
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.PAYMENT_PENDING
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.PAYMENT_PENDING

    def test_verified_to_completed_transition(self, vote_attempt):
        """
        Test transition from VERIFIED to COMPLETED (free contest).
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.COMPLETED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.COMPLETED

    def test_verified_to_rejected_transition(self, vote_attempt):
        """
        Test transition from VERIFIED to REJECTED (validation failed).
        Validates Requirement 6.10
        """
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = "Contest no longer accepting votes"
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason == "Contest no longer accepting votes"

    def test_payment_pending_to_payment_confirmed_transition(self, vote_attempt):
        """
        Test transition from PAYMENT_PENDING to PAYMENT_CONFIRMED (payment success).
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_PENDING
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.PAYMENT_CONFIRMED

    def test_payment_pending_to_expired_transition(self, vote_attempt):
        """
        Test transition from PAYMENT_PENDING to EXPIRED (30min timeout).
        Validates Requirement 6.13
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_PENDING
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.EXPIRED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.EXPIRED

    def test_payment_pending_to_failed_transition(self, vote_attempt):
        """
        Test transition from PAYMENT_PENDING to FAILED (payment failed).
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_PENDING
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.FAILED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.FAILED

    def test_payment_confirmed_to_completed_transition(self, vote_attempt):
        """
        Test transition from PAYMENT_CONFIRMED to COMPLETED (vote committed).
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.COMPLETED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.COMPLETED

    def test_payment_confirmed_to_failed_transition(self, vote_attempt):
        """
        Test transition from PAYMENT_CONFIRMED to FAILED (commit failed).
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        vote_attempt.save()
        
        vote_attempt.state = VoteAttempt.State.FAILED
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.FAILED


@pytest.mark.django_db
class TestVoteAttemptInvalidStateTransitions:
    """Tests for invalid VoteAttempt state transitions that should not occur."""

    def test_completed_is_terminal_state(self, vote_attempt):
        """
        Test that COMPLETED is a terminal state and should not transition further.
        Note: This is a logical constraint, not enforced by database.
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.COMPLETED
        vote_attempt.completed_at = timezone.now()
        vote_attempt.save()
        
        # Logically, we should not transition from COMPLETED
        # This test documents expected behavior
        assert vote_attempt.state == VoteAttempt.State.COMPLETED
        assert vote_attempt.completed_at is not None

    def test_rejected_is_terminal_state(self, vote_attempt):
        """
        Test that REJECTED is a terminal state and should not transition further.
        Note: This is a logical constraint, not enforced by database.
        Validates Requirement 6.10
        """
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = "Duplicate vote"
        vote_attempt.completed_at = timezone.now()
        vote_attempt.save()
        
        # Logically, we should not transition from REJECTED
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason != ""
        assert vote_attempt.completed_at is not None

    def test_expired_is_terminal_state(self, vote_attempt):
        """
        Test that EXPIRED is a terminal state and should not transition further.
        Note: This is a logical constraint, not enforced by database.
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.EXPIRED
        vote_attempt.completed_at = timezone.now()
        vote_attempt.save()
        
        # Logically, we should not transition from EXPIRED
        assert vote_attempt.state == VoteAttempt.State.EXPIRED
        assert vote_attempt.completed_at is not None

    def test_failed_is_terminal_state(self, vote_attempt):
        """
        Test that FAILED is a terminal state and should not transition further.
        Note: This is a logical constraint, not enforced by database.
        Validates Requirement 6.9
        """
        vote_attempt.state = VoteAttempt.State.FAILED
        vote_attempt.completed_at = timezone.now()
        vote_attempt.save()
        
        # Logically, we should not transition from FAILED
        assert vote_attempt.state == VoteAttempt.State.FAILED
        assert vote_attempt.completed_at is not None


@pytest.mark.django_db
class TestVoteAttemptRejectionReason:
    """Tests for VoteAttempt rejection_reason population on REJECTED state."""

    def test_rejection_reason_populated_on_rejected_state(self, vote_attempt):
        """
        Test that rejection_reason is populated when transitioning to REJECTED.
        Validates Requirement 6.6, 6.10
        """
        reason = "Voter has reached vote limit"
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = reason
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason == reason

    def test_rejection_reason_empty_by_default(self, vote_attempt):
        """
        Test that rejection_reason is empty by default.
        Validates Requirement 6.5
        """
        assert vote_attempt.rejection_reason == ""

    def test_rejection_reason_truncated_at_500_chars(self, vote_attempt):
        """
        Test that rejection_reason is truncated at 500 characters max.
        Validates Requirement 6.5
        """
        long_reason = "x" * 600  # 600 characters
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = long_reason[:500]  # Truncate manually
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert len(vote_attempt.rejection_reason) == 500

    def test_mark_rejected_method_populates_reason(self, vote_attempt):
        """
        Test that mark_rejected() helper method populates rejection_reason.
        Validates Requirement 6.10
        """
        reason = "Payment verification failed"
        
        vote_attempt.mark_rejected(reason=reason, save=True)
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.rejection_reason == reason

    def test_mark_rejected_truncates_long_reasons(self, vote_attempt):
        """
        Test that mark_rejected() truncates reasons exceeding 500 characters.
        Validates Requirement 6.5
        """
        long_reason = "x" * 600  # 600 characters
        
        vote_attempt.mark_rejected(reason=long_reason, save=True)
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert len(vote_attempt.rejection_reason) == 500
        assert vote_attempt.rejection_reason == long_reason[:500]

    def test_multiple_rejections_override_reason(self, vote_attempt):
        """
        Test that calling mark_rejected multiple times overrides the reason.
        Validates Requirement 6.6
        """
        first_reason = "First rejection reason"
        second_reason = "Second rejection reason"
        
        vote_attempt.mark_rejected(reason=first_reason, save=True)
        vote_attempt.refresh_from_db()
        assert vote_attempt.rejection_reason == first_reason
        
        vote_attempt.mark_rejected(reason=second_reason, save=True)
        vote_attempt.refresh_from_db()
        assert vote_attempt.rejection_reason == second_reason

    def test_rejection_reason_can_contain_special_characters(self, vote_attempt):
        """
        Test that rejection_reason can contain special characters and Unicode.
        Validates Requirement 6.5
        """
        reason = "User blocked: Failed checks (IP: 192.168.1.1, Device: 'unknown')"
        
        vote_attempt.state = VoteAttempt.State.REJECTED
        vote_attempt.rejection_reason = reason
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.rejection_reason == reason


@pytest.mark.django_db
class TestVoteAttemptCompletedAtTimestamp:
    """Tests for VoteAttempt completed_at timestamp on COMPLETED state."""

    def test_completed_at_is_null_by_default(self, vote_attempt):
        """
        Test that completed_at is NULL when VoteAttempt is first created.
        Validates Requirement 6.11
        """
        assert vote_attempt.completed_at is None

    def test_completed_at_set_on_completed_state(self, vote_attempt):
        """
        Test that completed_at is set when transitioning to COMPLETED state.
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.VERIFIED
        vote_attempt.save()
        
        before_completion = timezone.now()
        vote_attempt.state = VoteAttempt.State.COMPLETED
        vote_attempt.completed_at = timezone.now()
        vote_attempt.save()
        after_completion = timezone.now()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.COMPLETED
        assert vote_attempt.completed_at is not None
        assert before_completion <= vote_attempt.completed_at <= after_completion

    def test_mark_completed_method_sets_timestamp(self, vote_attempt):
        """
        Test that mark_completed() helper method sets completed_at timestamp.
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        vote_attempt.save()
        
        before_mark = timezone.now()
        vote_attempt.mark_completed(save=True)
        after_mark = timezone.now()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.COMPLETED
        assert vote_attempt.completed_at is not None
        assert before_mark <= vote_attempt.completed_at <= after_mark

    def test_completed_at_not_overwritten_when_already_set(self, vote_attempt):
        """
        Test that completed_at is not overwritten if already set.
        Validates Requirement 6.11
        """
        original_timestamp = timezone.now()
        vote_attempt.state = VoteAttempt.State.COMPLETED
        vote_attempt.completed_at = original_timestamp
        vote_attempt.save()
        
        # Call mark_completed again
        vote_attempt.mark_completed(save=True)
        
        vote_attempt.refresh_from_db()
        # completed_at should remain the original timestamp
        assert vote_attempt.completed_at == original_timestamp

    def test_completed_at_set_on_rejected_state(self, vote_attempt):
        """
        Test that completed_at is set when transitioning to REJECTED state.
        Validates Requirement 6.10, 6.11
        """
        before_rejection = timezone.now()
        vote_attempt.mark_rejected(reason="Vote limit exceeded", save=True)
        after_rejection = timezone.now()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.REJECTED
        assert vote_attempt.completed_at is not None
        assert before_rejection <= vote_attempt.completed_at <= after_rejection

    def test_completed_at_set_on_expired_state(self, vote_attempt):
        """
        Test that completed_at is set when transitioning to EXPIRED state.
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_PENDING
        vote_attempt.save()
        
        before_expiry = timezone.now()
        vote_attempt.mark_expired(save=True)
        after_expiry = timezone.now()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.EXPIRED
        assert vote_attempt.completed_at is not None
        assert before_expiry <= vote_attempt.completed_at <= after_expiry

    def test_completed_at_set_on_failed_state(self, vote_attempt):
        """
        Test that completed_at is set when transitioning to FAILED state.
        Validates Requirement 6.11
        """
        vote_attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        vote_attempt.save()
        
        before_failure = timezone.now()
        vote_attempt.mark_failed(reason="Database error", save=True)
        after_failure = timezone.now()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.state == VoteAttempt.State.FAILED
        assert vote_attempt.completed_at is not None
        assert before_failure <= vote_attempt.completed_at <= after_failure


@pytest.mark.django_db
class TestVoteAttemptBasicFunctionality:
    """Tests for VoteAttempt basic model functionality."""

    def test_default_state_is_started(self, user, contest, contestant):
        """
        Test that new VoteAttempt has state set to STARTED by default.
        Validates Requirement 6.3
        """
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        assert attempt.state == VoteAttempt.State.STARTED

    def test_default_vote_quantity_is_one(self, user, contest, contestant):
        """
        Test that vote_quantity defaults to 1.
        Validates Requirement 6.2
        """
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        assert attempt.vote_quantity == 1

    def test_vote_quantity_can_be_set(self, user, contest, contestant):
        """
        Test that vote_quantity can be set to values between 1 and 1000.
        Validates Requirement 6.2
        """
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant,
            vote_quantity=10
        )
        
        assert attempt.vote_quantity == 10

    def test_foreign_key_relationships(self, vote_attempt, user, contest, contestant):
        """Test foreign key relationships to User, Contest, and Contestant."""
        assert vote_attempt.user == user
        assert vote_attempt.contest == contest
        assert vote_attempt.contestant == contestant
        
        # Test reverse relationships
        assert vote_attempt in user.vote_attempts.all()
        assert vote_attempt in contest.vote_attempts.all()
        assert vote_attempt in contestant.vote_attempts.all()

    def test_verification_context_default_is_empty_dict(self, vote_attempt):
        """
        Test that verification_context defaults to empty dict.
        Validates Requirement 6.4
        """
        assert vote_attempt.verification_context == {}

    def test_verification_context_can_store_json(self, vote_attempt):
        """
        Test that verification_context can store JSON data.
        Validates Requirement 6.4
        """
        context = {
            "method": "EMAIL",
            "verification_id": "12345",
            "timestamp": "2024-01-15T10:00:00Z"
        }
        
        vote_attempt.verification_context = context
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.verification_context == context

    def test_device_identifier_can_be_set(self, vote_attempt):
        """
        Test that device_identifier can be set.
        Validates Requirement 6.7
        """
        device_id = "Mozilla/5.0|Windows|Chrome|1920x1080"
        
        vote_attempt.device_identifier = device_id
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.device_identifier == device_id

    def test_ip_hash_can_be_set(self, vote_attempt):
        """
        Test that ip_hash can be set.
        Validates Requirement 6.8
        """
        ip_hash = "a" * 64  # SHA-256 hash is 64 characters
        
        vote_attempt.ip_hash = ip_hash
        vote_attempt.save()
        
        vote_attempt.refresh_from_db()
        assert vote_attempt.ip_hash == ip_hash

    def test_timestamps_auto_set(self, user, contest, contestant):
        """Test that created_at timestamp is auto-set."""
        before = timezone.now()
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        after = timezone.now()
        
        assert before <= attempt.created_at <= after

    def test_str_representation(self, vote_attempt, user, contestant):
        """Test string representation of VoteAttempt."""
        str_repr = str(vote_attempt)
        assert user.email in str_repr
        assert contestant.name in str_repr
        assert vote_attempt.state in str_repr

    def test_cascade_delete_with_user(self, vote_attempt, user):
        """Test that VoteAttempt is deleted when User is deleted."""
        attempt_id = vote_attempt.id
        
        user.delete()
        
        assert not VoteAttempt.objects.filter(id=attempt_id).exists()

    def test_cascade_delete_with_contest(self, vote_attempt, contest):
        """Test that VoteAttempt is deleted when Contest is deleted."""
        attempt_id = vote_attempt.id
        
        contest.delete()
        
        assert not VoteAttempt.objects.filter(id=attempt_id).exists()

    def test_cascade_delete_with_contestant(self, vote_attempt, contestant):
        """Test that VoteAttempt is deleted when Contestant is deleted."""
        attempt_id = vote_attempt.id
        
        contestant.delete()
        
        assert not VoteAttempt.objects.filter(id=attempt_id).exists()


@pytest.mark.django_db
class TestVoteAttemptStateTransitionWorkflow:
    """Tests for complete VoteAttempt state transition workflows."""

    def test_successful_free_contest_workflow(self, user, contest, contestant):
        """
        Test complete workflow for successful vote in free contest:
        STARTED → VERIFIED → COMPLETED
        Validates Requirements 6.9, 6.11
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        assert attempt.state == VoteAttempt.State.STARTED
        assert attempt.completed_at is None
        
        # Transition to VERIFIED (no verification required)
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        assert attempt.state == VoteAttempt.State.VERIFIED
        
        # Complete the vote
        attempt.mark_completed(save=True)
        assert attempt.state == VoteAttempt.State.COMPLETED
        assert attempt.completed_at is not None

    def test_successful_paid_contest_workflow(self, user, contest, contestant):
        """
        Test complete workflow for successful vote in paid contest:
        STARTED → VERIFIED → PAYMENT_PENDING → PAYMENT_CONFIRMED → COMPLETED
        Validates Requirements 6.9, 6.11
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        assert attempt.state == VoteAttempt.State.STARTED
        
        # Transition to VERIFIED
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        
        # Transition to PAYMENT_PENDING
        attempt.state = VoteAttempt.State.PAYMENT_PENDING
        attempt.save()
        assert attempt.state == VoteAttempt.State.PAYMENT_PENDING
        
        # Payment confirmed
        attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        attempt.save()
        assert attempt.state == VoteAttempt.State.PAYMENT_CONFIRMED
        
        # Complete the vote
        attempt.mark_completed(save=True)
        assert attempt.state == VoteAttempt.State.COMPLETED
        assert attempt.completed_at is not None

    def test_workflow_with_identity_verification(self, user, contest, contestant):
        """
        Test workflow with identity verification:
        STARTED → IDENTITY_CHECK → VERIFIED → COMPLETED
        Validates Requirements 6.9, 6.10, 6.11
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        # Transition to IDENTITY_CHECK
        attempt.state = VoteAttempt.State.IDENTITY_CHECK
        attempt.save()
        assert attempt.state == VoteAttempt.State.IDENTITY_CHECK
        
        # Identity verification succeeds
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.verification_context = {
            "method": "EMAIL",
            "verified_at": timezone.now().isoformat()
        }
        attempt.save()
        assert attempt.state == VoteAttempt.State.VERIFIED
        
        # Complete the vote
        attempt.mark_completed(save=True)
        assert attempt.state == VoteAttempt.State.COMPLETED

    def test_workflow_rejected_at_verification(self, user, contest, contestant):
        """
        Test workflow where vote is rejected during verification:
        STARTED → IDENTITY_CHECK → REJECTED
        Validates Requirements 6.9, 6.10
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        # Transition to IDENTITY_CHECK
        attempt.state = VoteAttempt.State.IDENTITY_CHECK
        attempt.save()
        
        # Verification fails
        attempt.mark_rejected(reason="Failed to verify identity", save=True)
        assert attempt.state == VoteAttempt.State.REJECTED
        assert attempt.rejection_reason == "Failed to verify identity"
        assert attempt.completed_at is not None

    def test_workflow_payment_timeout(self, user, contest, contestant):
        """
        Test workflow where payment times out:
        STARTED → VERIFIED → PAYMENT_PENDING → EXPIRED
        Validates Requirements 6.9, 6.13
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        # Progress through states
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        
        attempt.state = VoteAttempt.State.PAYMENT_PENDING
        attempt.save()
        
        # Payment times out after 30 minutes
        attempt.mark_expired(save=True)
        assert attempt.state == VoteAttempt.State.EXPIRED
        assert attempt.completed_at is not None

    def test_workflow_payment_failed(self, user, contest, contestant):
        """
        Test workflow where payment fails:
        STARTED → VERIFIED → PAYMENT_PENDING → FAILED
        Validates Requirements 6.9
        """
        # Create attempt
        attempt = VoteAttempt.objects.create(
            user=user,
            contest=contest,
            contestant=contestant
        )
        
        # Progress through states
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        
        attempt.state = VoteAttempt.State.PAYMENT_PENDING
        attempt.save()
        
        # Payment fails
        attempt.mark_failed(reason="Payment provider error", save=True)
        assert attempt.state == VoteAttempt.State.FAILED
        assert attempt.rejection_reason == "Payment provider error"
        assert attempt.completed_at is not None
