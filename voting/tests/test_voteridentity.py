"""
Unit tests for VoterIdentity model.

Tests unique constraints, default verification status, and verified_at
timestamp behavior for the VoterIdentity model.

Validates Requirements: 4.1, 4.2, 4.3, 4.5
"""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from accounts.models import User
from polls.models import Contest
from voting.models import VoterIdentity


@pytest.fixture
def user():
    """Create a test user for voter identity creation."""
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
    """Create a test contest for VoterIdentity creation."""
    return Contest.objects.create(
        title="Test Contest",
        slug="test-contest",
        organizer=organizer,
        state=Contest.State.DRAFT
    )


@pytest.mark.django_db
class TestVoterIdentityUniqueConstraint:
    """Tests for VoterIdentity unique constraint on (user, contest)."""

    def test_unique_constraint_allows_one_identity_per_user_per_contest(self, user, contest):
        """
        Test unique constraint allows creating one VoterIdentity per user per contest.
        Validates Requirement 4.1
        """
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        assert identity.user == user
        assert identity.contest == contest
        assert VoterIdentity.objects.filter(user=user, contest=contest).count() == 1

    def test_unique_constraint_prevents_duplicate_identity_for_same_user_contest(self, user, contest):
        """
        Test unique constraint prevents creating duplicate VoterIdentity for same (user, contest).
        Validates Requirement 4.1
        """
        # Create first identity
        VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        # Attempt to create duplicate should raise IntegrityError
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VoterIdentity.objects.create(
                    user=user,
                    contest=contest
                )
        
        error = str(exc_info.value).lower()
        assert (
            "unique_voter_identity_per_contest" in error
            or "duplicate" in error
            or "voting_voteridentity.user_id, voting_voteridentity.contest_id" in error
        )

    def test_unique_constraint_allows_same_user_different_contests(self, user, organizer):
        """
        Test unique constraint allows same user to have identities in different contests.
        Validates Requirement 4.1
        """
        contest1 = Contest.objects.create(
            title="Contest 1",
            slug="contest-1",
            organizer=organizer,
            state=Contest.State.DRAFT
        )
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=organizer,
            state=Contest.State.DRAFT
        )
        
        identity1 = VoterIdentity.objects.create(
            user=user,
            contest=contest1
        )
        identity2 = VoterIdentity.objects.create(
            user=user,
            contest=contest2
        )
        
        assert identity1.user == user
        assert identity2.user == user
        assert identity1.contest == contest1
        assert identity2.contest == contest2
        assert identity1.id != identity2.id

    def test_unique_constraint_allows_different_users_same_contest(self, contest):
        """
        Test unique constraint allows different users to have identities in same contest.
        Validates Requirement 4.1
        """
        user1 = User.objects.create_user(
            email="voter1@example.com",
            password="testpass123",
            name="Voter 1"
        )
        user2 = User.objects.create_user(
            email="voter2@example.com",
            password="testpass123",
            name="Voter 2"
        )
        
        identity1 = VoterIdentity.objects.create(
            user=user1,
            contest=contest
        )
        identity2 = VoterIdentity.objects.create(
            user=user2,
            contest=contest
        )
        
        assert identity1.contest == contest
        assert identity2.contest == contest
        assert identity1.user == user1
        assert identity2.user == user2
        assert identity1.id != identity2.id


@pytest.mark.django_db
class TestVoterIdentityDefaultVerificationStatus:
    """Tests for VoterIdentity default verification_status."""

    def test_default_verification_status_is_unverified(self, user, contest):
        """
        Test that new VoterIdentity has verification_status set to UNVERIFIED by default.
        Validates Requirement 4.2, 4.3
        """
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        assert identity.verification_status == VoterIdentity.VerificationStatus.UNVERIFIED

    def test_default_verification_status_without_explicit_value(self, user, contest):
        """
        Test verification_status defaults to UNVERIFIED when not explicitly set.
        Validates Requirement 4.3
        """
        identity = VoterIdentity(
            user=user,
            contest=contest
            # verification_status not explicitly set
        )
        identity.save()
        
        identity.refresh_from_db()
        assert identity.verification_status == VoterIdentity.VerificationStatus.UNVERIFIED

    def test_can_override_default_verification_status(self, user, contest):
        """
        Test that verification_status can be explicitly set to a different value on creation.
        Validates Requirement 4.2
        """
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )
        
        assert identity.verification_status == VoterIdentity.VerificationStatus.VERIFIED

    def test_verification_status_accepts_all_valid_choices(self, user, organizer):
        """
        Test that verification_status accepts all valid enum values.
        Validates Requirement 4.2
        """
        all_statuses = [
            VoterIdentity.VerificationStatus.UNVERIFIED,
            VoterIdentity.VerificationStatus.PENDING,
            VoterIdentity.VerificationStatus.VERIFIED,
            VoterIdentity.VerificationStatus.EXPIRED,
            VoterIdentity.VerificationStatus.FAILED,
        ]
        
        for idx, status in enumerate(all_statuses):
            contest = Contest.objects.create(
                title=f"Contest {idx}",
                slug=f"contest-{idx}",
                organizer=organizer,
                state=Contest.State.DRAFT
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=contest,
                verification_status=status
            )
            
            assert identity.verification_status == status


@pytest.mark.django_db
class TestVoterIdentityVerifiedAtTimestamp:
    """Tests for VoterIdentity verified_at timestamp behavior."""

    def test_verified_at_is_null_on_creation(self, user, contest):
        """
        Test that verified_at is NULL when VoterIdentity is first created.
        Validates Requirement 4.4
        """
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        assert identity.verified_at is None

    def test_verified_at_remains_null_for_non_verified_statuses(self, user, organizer):
        """
        Test that verified_at remains NULL for statuses other than VERIFIED.
        Validates Requirement 4.4
        """
        non_verified_statuses = [
            VoterIdentity.VerificationStatus.UNVERIFIED,
            VoterIdentity.VerificationStatus.PENDING,
            VoterIdentity.VerificationStatus.EXPIRED,
            VoterIdentity.VerificationStatus.FAILED,
        ]
        
        for idx, status in enumerate(non_verified_statuses):
            contest = Contest.objects.create(
                title=f"Contest {idx}",
                slug=f"contest-{idx}",
                organizer=organizer,
                state=Contest.State.DRAFT
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=contest,
                verification_status=status
            )
            
            assert identity.verified_at is None, f"verified_at should be None for status {status}"

    def test_verified_at_set_when_status_transitions_to_verified(self, user, contest):
        """
        Test that verified_at is set to current timestamp when status transitions to VERIFIED.
        Validates Requirement 4.5
        """
        # Create identity with UNVERIFIED status
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            verification_status=VoterIdentity.VerificationStatus.UNVERIFIED
        )
        
        assert identity.verified_at is None
        
        # Transition to VERIFIED
        before_transition = timezone.now()
        identity.verification_status = VoterIdentity.VerificationStatus.VERIFIED
        identity.verified_at = timezone.now()
        identity.save()
        after_transition = timezone.now()
        
        identity.refresh_from_db()
        assert identity.verified_at is not None
        assert before_transition <= identity.verified_at <= after_transition

    def test_verified_at_set_using_mark_verified_method(self, user, contest):
        """
        Test that mark_verified() method sets verified_at timestamp correctly.
        Validates Requirement 4.5
        """
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            verification_status=VoterIdentity.VerificationStatus.UNVERIFIED
        )
        
        assert identity.verified_at is None
        
        # Use the mark_verified() helper method
        before_mark = timezone.now()
        identity.mark_verified(save=True)
        after_mark = timezone.now()
        
        identity.refresh_from_db()
        assert identity.verification_status == VoterIdentity.VerificationStatus.VERIFIED
        assert identity.verified_at is not None
        assert before_mark <= identity.verified_at <= after_mark

    def test_verified_at_not_overwritten_when_already_set(self, user, contest):
        """
        Test that verified_at is not overwritten if already set when mark_verified is called.
        Validates Requirement 4.5
        """
        original_timestamp = timezone.now()
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED,
            verified_at=original_timestamp
        )
        
        # Call mark_verified again
        identity.mark_verified(save=True)
        
        identity.refresh_from_db()
        # verified_at should remain the original timestamp
        assert identity.verified_at == original_timestamp

    def test_verified_at_can_be_explicitly_set(self, user, contest):
        """
        Test that verified_at can be explicitly set to a specific timestamp.
        Validates Requirement 4.4
        """
        specific_timestamp = timezone.now()
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED,
            verified_at=specific_timestamp
        )
        
        identity.refresh_from_db()
        assert identity.verified_at == specific_timestamp


@pytest.mark.django_db
class TestVoterIdentityBasicFunctionality:
    """Tests for VoterIdentity basic model functionality."""

    def test_foreign_key_relationship_to_user(self, user, contest):
        """Test foreign key relationship to User model."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        # Access from identity to user
        assert identity.user == user
        
        # Access from user to identities
        assert identity in user.voter_identities.all()

    def test_foreign_key_relationship_to_contest(self, user, contest):
        """Test foreign key relationship to Contest model."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        # Access from identity to contest
        assert identity.contest == contest
        
        # Access from contest to identities
        assert identity in contest.voter_identities.all()

    def test_cascade_delete_with_user(self, user, contest):
        """Test that VoterIdentity is deleted when User is deleted."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        identity_id = identity.id
        
        # Delete user
        user.delete()
        
        # Identity should be deleted too
        assert not VoterIdentity.objects.filter(id=identity_id).exists()

    def test_cascade_delete_with_contest(self, user, contest):
        """Test that VoterIdentity is deleted when Contest is deleted."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        identity_id = identity.id
        
        # Delete contest
        contest.delete()
        
        # Identity should be deleted too
        assert not VoterIdentity.objects.filter(id=identity_id).exists()

    def test_str_representation(self, user, contest):
        """Test string representation of VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        str_repr = str(identity)
        assert user.email in str_repr
        assert contest.title in str_repr
        assert identity.verification_status in str_repr

    def test_timestamps_auto_set(self, user, contest):
        """Test that created_at and updated_at timestamps are auto-set."""
        before = timezone.now()
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        after = timezone.now()
        
        assert before <= identity.created_at <= after
        assert before <= identity.updated_at <= after

    def test_updated_at_changes_on_update(self, user, contest):
        """Test that updated_at timestamp changes when model is updated."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        original_updated_at = identity.updated_at
        
        # Wait a tiny bit and update
        import time
        time.sleep(0.01)
        
        identity.verification_status = VoterIdentity.VerificationStatus.PENDING
        identity.save()
        
        identity.refresh_from_db()
        assert identity.updated_at > original_updated_at

    def test_expires_at_field_is_optional(self, user, contest):
        """Test that expires_at field is optional and can be NULL."""
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest
        )
        
        assert identity.expires_at is None

    def test_expires_at_can_be_set(self, user, contest):
        """Test that expires_at can be set to a future timestamp."""
        from datetime import timedelta
        
        future_time = timezone.now() + timedelta(days=30)
        identity = VoterIdentity.objects.create(
            user=user,
            contest=contest,
            expires_at=future_time
        )
        
        identity.refresh_from_db()
        assert identity.expires_at == future_time
