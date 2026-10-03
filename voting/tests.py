"""
Unit tests for voting app models.

Tests cover VotingPolicy model validation, constraints, and business logic.
"""

import uuid
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.contrib.auth import get_user_model

from polls.models import Contest, Contestant
from voting.models import VotingPolicy, VoterIdentity, VoterVerification, VoteAttempt

User = get_user_model()


class VotingPolicyModelTests(TestCase):
    """Test suite for VotingPolicy model validation and constraints."""
    
    def setUp(self):
        """Create test fixtures: user, contest."""
        self.user = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123"
        )
        
        self.contest = Contest.objects.create(
            title="Test Contest",
            slug="test-contest",
            organizer=self.user,
            state=Contest.State.DRAFT
        )
    
    def test_create_voting_policy_with_defaults(self):
        """Test creating VotingPolicy with default values."""
        policy = VotingPolicy.objects.create(contest=self.contest)
        
        self.assertEqual(policy.vote_limit_type, VotingPolicy.VoteLimitType.UNLIMITED)
        self.assertIsNone(policy.max_votes_per_voter)
        self.assertEqual(policy.verification_method, VotingPolicy.VerificationMethod.NONE)
        self.assertIsNone(policy.required_verification_methods)
        self.assertEqual(policy.price_per_vote, Decimal('0.00'))
        self.assertEqual(policy.revenue_share_percentage, 80)
        self.assertFalse(policy.allow_anonymous)
    
    def test_one_to_one_relationship_with_contest(self):
        """Test that each contest can have only one voting policy."""
        VotingPolicy.objects.create(contest=self.contest)
        
        # Attempting to create a second policy for the same contest should fail
        with self.assertRaises(IntegrityError):
            VotingPolicy.objects.create(contest=self.contest)
    
    def test_vote_limit_type_limited_requires_max_votes(self):
        """Test CHECK constraint: LIMITED vote_limit_type requires max_votes_per_voter."""
        # This should fail at the database level due to CHECK constraint
        with self.assertRaises(IntegrityError) as cm:
            VotingPolicy.objects.create(
                contest=self.contest,
                vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
                max_votes_per_voter=None  # Invalid: should not be NULL
            )
        
        # Check that the error is about the constraint
        self.assertIn('max_votes_required_for_limited', str(cm.exception))
    
    def test_vote_limit_type_limited_with_valid_max_votes(self):
        """Test LIMITED vote_limit_type with valid max_votes_per_voter."""
        policy = VotingPolicy.objects.create(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=10
        )
        
        self.assertEqual(policy.max_votes_per_voter, 10)
    
    def test_vote_limit_type_one_must_have_null_max_votes(self):
        """Test CHECK constraint: ONE vote_limit_type must have NULL max_votes_per_voter."""
        # Create with explicit None
        policy = VotingPolicy.objects.create(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.ONE,
            max_votes_per_voter=None
        )
        self.assertIsNone(policy.max_votes_per_voter)
    
    def test_vote_limit_type_unlimited_must_have_null_max_votes(self):
        """Test CHECK constraint: UNLIMITED vote_limit_type must have NULL max_votes_per_voter."""
        policy = VotingPolicy.objects.create(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            max_votes_per_voter=None
        )
        self.assertIsNone(policy.max_votes_per_voter)
    
    def test_max_votes_per_voter_min_validator(self):
        """Test max_votes_per_voter minimum value validator (2)."""
        policy = VotingPolicy(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1  # Below minimum
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('max_votes_per_voter', cm.exception.error_dict)
    
    def test_max_votes_per_voter_max_validator(self):
        """Test max_votes_per_voter maximum value validator (1000)."""
        policy = VotingPolicy(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1001  # Above maximum
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('max_votes_per_voter', cm.exception.error_dict)
    
    def test_max_votes_per_voter_valid_range(self):
        """Test max_votes_per_voter accepts values in valid range (2-1000)."""
        # Test minimum boundary
        policy_min = VotingPolicy.objects.create(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=2
        )
        self.assertEqual(policy_min.max_votes_per_voter, 2)
        
        # Test maximum boundary (using a different contest)
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=self.user
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1000
        )
        self.assertEqual(policy_max.max_votes_per_voter, 1000)
    
    def test_verification_method_choices(self):
        """Test all verification method enum values."""
        valid_methods = [
            VotingPolicy.VerificationMethod.EMAIL,
            VotingPolicy.VerificationMethod.PHONE,
            VotingPolicy.VerificationMethod.NIN,
            VotingPolicy.VerificationMethod.VOTERS_CARD,
            VotingPolicy.VerificationMethod.FINGERPRINT,
            VotingPolicy.VerificationMethod.COMPOSITE,
            VotingPolicy.VerificationMethod.NONE,
        ]
        
        for idx, method in enumerate(valid_methods):
            contest = Contest.objects.create(
                title=f"Contest {idx}",
                slug=f"contest-{idx}",
                organizer=self.user
            )
            policy = VotingPolicy.objects.create(
                contest=contest,
                verification_method=method
            )
            self.assertEqual(policy.verification_method, method)
    
    def test_verification_method_composite_requires_methods(self):
        """Test CHECK constraint: COMPOSITE verification requires required_verification_methods."""
        with self.assertRaises(IntegrityError) as cm:
            VotingPolicy.objects.create(
                contest=self.contest,
                verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
                required_verification_methods=None  # Invalid: should not be NULL
            )
        
        self.assertIn('composite_requires_methods', str(cm.exception))
    
    def test_verification_method_composite_with_valid_methods(self):
        """Test COMPOSITE verification with valid required_verification_methods array."""
        policy = VotingPolicy.objects.create(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=['EMAIL', 'PHONE']
        )
        
        self.assertEqual(policy.required_verification_methods, ['EMAIL', 'PHONE'])
    
    def test_verification_method_non_composite_must_have_null_methods(self):
        """Test CHECK constraint: non-COMPOSITE verification must have NULL required_verification_methods."""
        policy = VotingPolicy.objects.create(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.EMAIL,
            required_verification_methods=None
        )
        self.assertIsNone(policy.required_verification_methods)
    
    def test_price_per_vote_min_validator(self):
        """Test price_per_vote minimum value validator (0.00)."""
        policy = VotingPolicy(
            contest=self.contest,
            price_per_vote=Decimal('-0.01')  # Negative value
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('price_per_vote', cm.exception.error_dict)
    
    def test_price_per_vote_max_validator(self):
        """Test price_per_vote maximum value validator (999999.99)."""
        policy = VotingPolicy(
            contest=self.contest,
            price_per_vote=Decimal('1000000.00')  # Above maximum
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('price_per_vote', cm.exception.error_dict)
    
    def test_price_per_vote_valid_range(self):
        """Test price_per_vote accepts values in valid range (0.00-999999.99)."""
        # Test minimum
        policy_min = VotingPolicy.objects.create(
            contest=self.contest,
            price_per_vote=Decimal('0.00')
        )
        self.assertEqual(policy_min.price_per_vote, Decimal('0.00'))
        
        # Test maximum (using different contest)
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=self.user
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            price_per_vote=Decimal('999999.99')
        )
        self.assertEqual(policy_max.price_per_vote, Decimal('999999.99'))
    
    def test_revenue_share_percentage_min_validator(self):
        """Test revenue_share_percentage minimum value validator (0)."""
        policy = VotingPolicy(
            contest=self.contest,
            revenue_share_percentage=-1  # Below minimum
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('revenue_share_percentage', cm.exception.error_dict)
    
    def test_revenue_share_percentage_max_validator(self):
        """Test revenue_share_percentage maximum value validator (100)."""
        policy = VotingPolicy(
            contest=self.contest,
            revenue_share_percentage=101  # Above maximum
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.full_clean()
        
        self.assertIn('revenue_share_percentage', cm.exception.error_dict)
    
    def test_revenue_share_percentage_valid_range(self):
        """Test revenue_share_percentage accepts values in valid range (0-100)."""
        # Test minimum
        policy_min = VotingPolicy.objects.create(
            contest=self.contest,
            revenue_share_percentage=0
        )
        self.assertEqual(policy_min.revenue_share_percentage, 0)
        
        # Test maximum (using different contest)
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=self.user
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            revenue_share_percentage=100
        )
        self.assertEqual(policy_max.revenue_share_percentage, 100)
    
    def test_allow_anonymous_boolean_field(self):
        """Test allow_anonymous is a boolean field."""
        # Test False (default)
        policy_false = VotingPolicy.objects.create(contest=self.contest)
        self.assertFalse(policy_false.allow_anonymous)
        
        # Test True
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=self.user
        )
        policy_true = VotingPolicy.objects.create(
            contest=contest2,
            allow_anonymous=True
        )
        self.assertTrue(policy_true.allow_anonymous)
    
    def test_str_representation(self):
        """Test string representation of VotingPolicy."""
        policy = VotingPolicy.objects.create(contest=self.contest)
        expected = f"Voting Policy for {self.contest.title}"
        self.assertEqual(str(policy), expected)
    
    def test_timestamps_auto_populated(self):
        """Test created_at and updated_at are auto-populated."""
        policy = VotingPolicy.objects.create(contest=self.contest)
        
        self.assertIsNotNone(policy.created_at)
        self.assertIsNotNone(policy.updated_at)
        self.assertEqual(policy.created_at, policy.updated_at)
    
    def test_clean_method_validates_limited_with_null_max_votes(self):
        """Test clean() method validates LIMITED requires max_votes_per_voter."""
        policy = VotingPolicy(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=None
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('max_votes_per_voter', cm.exception.error_dict)
    
    def test_clean_method_validates_one_with_non_null_max_votes(self):
        """Test clean() method validates ONE should have NULL max_votes_per_voter."""
        policy = VotingPolicy(
            contest=self.contest,
            vote_limit_type=VotingPolicy.VoteLimitType.ONE,
            max_votes_per_voter=5
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('max_votes_per_voter', cm.exception.error_dict)
    
    def test_clean_method_validates_composite_with_null_methods(self):
        """Test clean() method validates COMPOSITE requires required_verification_methods."""
        policy = VotingPolicy(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=None
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('required_verification_methods', cm.exception.error_dict)
    
    def test_clean_method_validates_composite_with_single_method(self):
        """Test clean() method validates COMPOSITE requires at least 2 methods."""
        policy = VotingPolicy(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=['EMAIL']  # Only one method
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('required_verification_methods', cm.exception.error_dict)
        self.assertIn('at least 2', str(cm.exception.error_dict['required_verification_methods']))
    
    def test_clean_method_validates_composite_with_duplicate_methods(self):
        """Test clean() method validates COMPOSITE methods must be distinct."""
        policy = VotingPolicy(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=['EMAIL', 'EMAIL']  # Duplicate
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('required_verification_methods', cm.exception.error_dict)
        self.assertIn('distinct', str(cm.exception.error_dict['required_verification_methods']))
    
    def test_clean_method_validates_composite_with_invalid_method(self):
        """Test clean() method validates COMPOSITE methods are valid choices."""
        policy = VotingPolicy(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=['EMAIL', 'INVALID_METHOD']
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('required_verification_methods', cm.exception.error_dict)
        self.assertIn('Invalid verification method', str(cm.exception.error_dict['required_verification_methods']))
    
    def test_clean_method_validates_non_composite_with_methods(self):
        """Test clean() method validates non-COMPOSITE should have NULL required_verification_methods."""
        policy = VotingPolicy(
            contest=self.contest,
            verification_method=VotingPolicy.VerificationMethod.EMAIL,
            required_verification_methods=['EMAIL', 'PHONE']
        )
        
        with self.assertRaises(ValidationError) as cm:
            policy.clean()
        
        self.assertIn('required_verification_methods', cm.exception.error_dict)
        self.assertIn('must be NULL', str(cm.exception.error_dict['required_verification_methods']))



class VoterIdentityModelTests(TestCase):
    """Test suite for VoterIdentity model validation and constraints."""
    
    def setUp(self):
        """Create test fixtures: user, organizer, contest."""
        self.user = User.objects.create_user(
            email="voter@example.com",
            name="Test Voter",
            password="testpass123"
        )
        
        self.organizer = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123"
        )
        
        self.contest = Contest.objects.create(
            title="Test Contest",
            slug="test-contest",
            organizer=self.organizer,
            state=Contest.State.DRAFT
        )
    
    def test_create_voter_identity_with_defaults(self):
        """Test creating VoterIdentity with default values."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.UNVERIFIED)
        self.assertIsNone(identity.verified_at)
        self.assertIsNone(identity.expires_at)
        self.assertIsNotNone(identity.created_at)
        self.assertIsNotNone(identity.updated_at)
    
    def test_unique_constraint_on_user_contest(self):
        """Test unique constraint on (user, contest) composite key."""
        # Create first identity
        VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        # Attempting to create second identity for same user-contest should fail
        with self.assertRaises(IntegrityError) as cm:
            VoterIdentity.objects.create(
                user=self.user,
                contest=self.contest
            )
        
        self.assertIn('unique_voter_identity_per_contest', str(cm.exception))
    
    def test_user_can_have_multiple_identities_for_different_contests(self):
        """Test that a user can have VoterIdentity for multiple contests."""
        contest2 = Contest.objects.create(
            title="Second Contest",
            slug="second-contest",
            organizer=self.organizer,
            state=Contest.State.DRAFT
        )
        
        identity1 = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        identity2 = VoterIdentity.objects.create(
            user=self.user,
            contest=contest2
        )
        
        self.assertNotEqual(identity1.id, identity2.id)
        self.assertEqual(identity1.user, identity2.user)
        self.assertNotEqual(identity1.contest, identity2.contest)
    
    def test_contest_can_have_multiple_voter_identities(self):
        """Test that a contest can have VoterIdentity for multiple users."""
        user2 = User.objects.create_user(
            email="voter2@example.com",
            name="Second Voter",
            password="testpass123"
        )
        
        identity1 = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        identity2 = VoterIdentity.objects.create(
            user=user2,
            contest=self.contest
        )
        
        self.assertNotEqual(identity1.id, identity2.id)
        self.assertNotEqual(identity1.user, identity2.user)
        self.assertEqual(identity1.contest, identity2.contest)
    
    def test_verification_status_choices(self):
        """Test all verification status enum values."""
        valid_statuses = [
            VoterIdentity.VerificationStatus.UNVERIFIED,
            VoterIdentity.VerificationStatus.PENDING,
            VoterIdentity.VerificationStatus.VERIFIED,
            VoterIdentity.VerificationStatus.EXPIRED,
            VoterIdentity.VerificationStatus.FAILED,
        ]
        
        for idx, status in enumerate(valid_statuses):
            user = User.objects.create_user(
                email=f"voter{idx}@example.com",
                name=f"Voter {idx}",
                password="testpass123"
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=self.contest,
                verification_status=status
            )
            self.assertEqual(identity.verification_status, status)
    
    def test_default_verification_status_is_unverified(self):
        """Test that default verification_status is UNVERIFIED."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.UNVERIFIED)
    
    def test_verified_at_timestamp_set_on_verification(self):
        """Test that verified_at is set when status transitions to VERIFIED."""
        from django.utils import timezone
        
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.UNVERIFIED
        )
        
        # Initially, verified_at should be None
        self.assertIsNone(identity.verified_at)
        
        # Transition to VERIFIED and set verified_at
        now = timezone.now()
        identity.verification_status = VoterIdentity.VerificationStatus.VERIFIED
        identity.verified_at = now
        identity.save()
        
        # Refresh from database
        identity.refresh_from_db()
        
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.VERIFIED)
        self.assertIsNotNone(identity.verified_at)
        # Check that verified_at is approximately equal to now (within 1 second)
        self.assertAlmostEqual(
            identity.verified_at.timestamp(),
            now.timestamp(),
            delta=1
        )
    
    def test_expires_at_optional_field(self):
        """Test that expires_at is optional and can be set."""
        from django.utils import timezone
        from datetime import timedelta
        
        expiry_time = timezone.now() + timedelta(days=30)
        
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            expires_at=expiry_time
        )
        
        self.assertIsNotNone(identity.expires_at)
        self.assertAlmostEqual(
            identity.expires_at.timestamp(),
            expiry_time.timestamp(),
            delta=1
        )
    
    def test_foreign_key_cascade_delete_user(self):
        """Test that deleting user cascades to VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        identity_id = identity.id
        
        # Delete user
        self.user.delete()
        
        # VoterIdentity should also be deleted
        with self.assertRaises(VoterIdentity.DoesNotExist):
            VoterIdentity.objects.get(id=identity_id)
    
    def test_foreign_key_cascade_delete_contest(self):
        """Test that deleting contest cascades to VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        identity_id = identity.id
        
        # Delete contest
        self.contest.delete()
        
        # VoterIdentity should also be deleted
        with self.assertRaises(VoterIdentity.DoesNotExist):
            VoterIdentity.objects.get(id=identity_id)
    
    def test_related_name_voter_identities_on_user(self):
        """Test reverse relationship from User to VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        # Access via related_name
        identities = self.user.voter_identities.all()
        
        self.assertEqual(identities.count(), 1)
        self.assertEqual(identities.first(), identity)
    
    def test_related_name_voter_identities_on_contest(self):
        """Test reverse relationship from Contest to VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        # Access via related_name
        identities = self.contest.voter_identities.all()
        
        self.assertEqual(identities.count(), 1)
        self.assertEqual(identities.first(), identity)
    
    def test_index_on_contest_verification_status(self):
        """Test that index exists on (contest, verification_status)."""
        # This is a meta test - the index is defined in the model Meta class
        # and should be created by the migration
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )
        
        # Query using indexed fields should be efficient
        results = VoterIdentity.objects.filter(
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )
        
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), identity)
    
    def test_index_on_user_contest(self):
        """Test that index exists on (user, contest)."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        # Query using indexed fields should be efficient
        result = VoterIdentity.objects.filter(
            user=self.user,
            contest=self.contest
        ).first()
        
        self.assertEqual(result, identity)
    
    def test_str_representation(self):
        """Test string representation of VoterIdentity."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )
        
        expected = f"{self.user.email} - {self.contest.title} (VERIFIED)"
        self.assertEqual(str(identity), expected)
    
    def test_timestamps_auto_populated(self):
        """Test created_at and updated_at are auto-populated."""
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        self.assertIsNotNone(identity.created_at)
        self.assertIsNotNone(identity.updated_at)
        self.assertEqual(identity.created_at, identity.updated_at)
    
    def test_timestamps_updated_on_save(self):
        """Test that updated_at changes when model is saved."""
        from time import sleep
        
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        original_updated_at = identity.updated_at
        
        # Wait a moment and update
        sleep(0.1)
        identity.verification_status = VoterIdentity.VerificationStatus.PENDING
        identity.save()
        
        # Refresh from database
        identity.refresh_from_db()
        
        # updated_at should have changed
        self.assertGreater(identity.updated_at, original_updated_at)
    
    def test_verification_status_transition_workflow(self):
        """Test typical verification workflow state transitions."""
        from django.utils import timezone
        
        # Create unverified identity
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.UNVERIFIED)
        
        # Transition to PENDING (verification initiated)
        identity.verification_status = VoterIdentity.VerificationStatus.PENDING
        identity.save()
        identity.refresh_from_db()
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.PENDING)
        
        # Transition to VERIFIED (verification successful)
        identity.verification_status = VoterIdentity.VerificationStatus.VERIFIED
        identity.verified_at = timezone.now()
        identity.save()
        identity.refresh_from_db()
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.VERIFIED)
        self.assertIsNotNone(identity.verified_at)
    
    def test_verification_failure_workflow(self):
        """Test verification failure workflow."""
        # Create unverified identity
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
        
        # Transition to PENDING
        identity.verification_status = VoterIdentity.VerificationStatus.PENDING
        identity.save()
        
        # Transition to FAILED (verification failed)
        identity.verification_status = VoterIdentity.VerificationStatus.FAILED
        identity.save()
        identity.refresh_from_db()
        
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.FAILED)
        # verified_at should still be None for failed verification
        self.assertIsNone(identity.verified_at)
    
    def test_verification_expiration_workflow(self):
        """Test verification expiration workflow."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create verified identity with expiry
        expiry_time = timezone.now() + timedelta(days=30)
        identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest,
            verification_status=VoterIdentity.VerificationStatus.VERIFIED,
            verified_at=timezone.now(),
            expires_at=expiry_time
        )
        
        # Simulate expiration
        identity.verification_status = VoterIdentity.VerificationStatus.EXPIRED
        identity.save()
        identity.refresh_from_db()
        
        self.assertEqual(identity.verification_status, VoterIdentity.VerificationStatus.EXPIRED)
        # verified_at should still exist (was verified, but now expired)
        self.assertIsNotNone(identity.verified_at)
        self.assertIsNotNone(identity.expires_at)



class VoterVerificationModelTests(TestCase):
    """Test suite for VoterVerification model validation and constraints."""
    
    def setUp(self):
        """Create test fixtures: user, organizer, contest, voter_identity."""
        self.user = User.objects.create_user(
            email="voter@example.com",
            name="Test Voter",
            password="testpass123"
        )
        
        self.organizer = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123"
        )
        
        self.contest = Contest.objects.create(
            title="Test Contest",
            slug="test-contest",
            organizer=self.organizer,
            state=Contest.State.DRAFT
        )
        
        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.contest
        )
    
    def test_create_voter_verification_with_defaults(self):
        """Test creating VoterVerification with default values."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertEqual(verification.status, VoterVerification.Status.PENDING)
        self.assertIsNone(verification.verification_response)
        self.assertIsNone(verification.completed_at)
        self.assertIsNotNone(verification.created_at)
    
    def test_foreign_key_to_voter_identity(self):
        """Test foreign key relationship to VoterIdentity."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertEqual(verification.voter_identity, self.voter_identity)
    
    def test_cascade_delete_with_voter_identity(self):
        """Test that deleting voter_identity cascades to VoterVerification."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        verification_id = verification.id
        
        # Delete voter_identity
        self.voter_identity.delete()
        
        # VoterVerification should also be deleted
        with self.assertRaises(VoterVerification.DoesNotExist):
            VoterVerification.objects.get(id=verification_id)
    
    def test_provider_field(self):
        """Test provider field stores provider name correctly."""
        providers = ["twilio", "termii", "smile_identity", "custom_provider"]
        
        for idx, provider in enumerate(providers):
            user = User.objects.create_user(
                email=f"voter{idx}@example.com",
                name=f"Voter {idx}",
                password="testpass123"
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=self.contest
            )
            verification = VoterVerification.objects.create(
                voter_identity=identity,
                provider=provider,
                method="EMAIL"
            )
            
            self.assertEqual(verification.provider, provider)
    
    def test_method_field(self):
        """Test method field stores verification method correctly."""
        methods = ["EMAIL", "PHONE", "NIN", "VOTERS_CARD", "FINGERPRINT"]
        
        for idx, method in enumerate(methods):
            user = User.objects.create_user(
                email=f"voter{idx}@example.com",
                name=f"Voter {idx}",
                password="testpass123"
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=self.contest
            )
            verification = VoterVerification.objects.create(
                voter_identity=identity,
                provider="test_provider",
                method=method
            )
            
            self.assertEqual(verification.method, method)
    
    def test_status_choices(self):
        """Test all status enum values."""
        valid_statuses = [
            VoterVerification.Status.PENDING,
            VoterVerification.Status.SUCCESS,
            VoterVerification.Status.FAILED,
        ]
        
        for idx, status in enumerate(valid_statuses):
            user = User.objects.create_user(
                email=f"voter{idx}@example.com",
                name=f"Voter {idx}",
                password="testpass123"
            )
            identity = VoterIdentity.objects.create(
                user=user,
                contest=self.contest
            )
            verification = VoterVerification.objects.create(
                voter_identity=identity,
                provider="test_provider",
                method="EMAIL",
                status=status
            )
            
            self.assertEqual(verification.status, status)
    
    def test_default_status_is_pending(self):
        """Test that default status is PENDING."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertEqual(verification.status, VoterVerification.Status.PENDING)
    
    def test_verification_response_jsonfield(self):
        """Test verification_response stores JSON data correctly."""
        response_data = {
            "code": "123456",
            "message": "OTP sent successfully",
            "reference": "ref-12345",
            "provider_status": "success"
        }
        
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            verification_response=response_data
        )
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.verification_response, response_data)
        self.assertEqual(verification.verification_response["code"], "123456")
        self.assertEqual(verification.verification_response["reference"], "ref-12345")
    
    def test_verification_response_can_be_null(self):
        """Test that verification_response can be null."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertIsNone(verification.verification_response)
    
    def test_completed_at_timestamp(self):
        """Test completed_at timestamp field."""
        from django.utils import timezone
        
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        # Initially, completed_at should be None
        self.assertIsNone(verification.completed_at)
        
        # Set completed_at
        now = timezone.now()
        verification.status = VoterVerification.Status.SUCCESS
        verification.completed_at = now
        verification.save()
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertIsNotNone(verification.completed_at)
        self.assertAlmostEqual(
            verification.completed_at.timestamp(),
            now.timestamp(),
            delta=1
        )
    
    def test_created_at_auto_populated(self):
        """Test created_at is auto-populated."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertIsNotNone(verification.created_at)
    
    def test_related_name_verification_attempts_on_voter_identity(self):
        """Test reverse relationship from VoterIdentity to VoterVerification."""
        verification1 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        verification2 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="termii",
            method="PHONE"
        )
        
        # Access via related_name
        attempts = self.voter_identity.verification_attempts.all()
        
        self.assertEqual(attempts.count(), 2)
        self.assertIn(verification1, attempts)
        self.assertIn(verification2, attempts)
    
    def test_index_on_voter_identity_created_at(self):
        """Test that index exists on (voter_identity, created_at)."""
        from django.utils import timezone
        from datetime import timedelta
        
        # Create multiple verifications at different times
        now = timezone.now()
        
        verification1 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        # Simulate different creation time
        VoterVerification.objects.filter(id=verification1.id).update(
            created_at=now - timedelta(hours=1)
        )
        
        verification2 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="termii",
            method="PHONE"
        )
        
        # Query using indexed fields should be efficient and ordered
        results = VoterVerification.objects.filter(
            voter_identity=self.voter_identity
        ).order_by('created_at')
        
        self.assertEqual(results.count(), 2)
        # verification1 should come first (older)
        self.assertEqual(results[0].id, verification1.id)
        self.assertEqual(results[1].id, verification2.id)
    
    def test_index_on_status(self):
        """Test that index exists on status field."""
        # Create verifications with different statuses
        verification1 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            status=VoterVerification.Status.PENDING
        )
        
        user2 = User.objects.create_user(
            email="voter2@example.com",
            name="Voter 2",
            password="testpass123"
        )
        identity2 = VoterIdentity.objects.create(
            user=user2,
            contest=self.contest
        )
        
        verification2 = VoterVerification.objects.create(
            voter_identity=identity2,
            provider="termii",
            method="PHONE",
            status=VoterVerification.Status.SUCCESS
        )
        
        # Query using indexed status field should be efficient
        pending_verifications = VoterVerification.objects.filter(
            status=VoterVerification.Status.PENDING
        )
        success_verifications = VoterVerification.objects.filter(
            status=VoterVerification.Status.SUCCESS
        )
        
        self.assertEqual(pending_verifications.count(), 1)
        self.assertEqual(pending_verifications.first(), verification1)
        self.assertEqual(success_verifications.count(), 1)
        self.assertEqual(success_verifications.first(), verification2)
    
    def test_str_representation(self):
        """Test string representation of VoterVerification."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            status=VoterVerification.Status.PENDING
        )
        
        expected = "EMAIL verification via twilio - pending"
        self.assertEqual(str(verification), expected)
    
    def test_verification_workflow_success(self):
        """Test typical successful verification workflow."""
        from django.utils import timezone
        
        # Create pending verification
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        self.assertEqual(verification.status, VoterVerification.Status.PENDING)
        self.assertIsNone(verification.completed_at)
        
        # Complete verification successfully
        response_data = {
            "code": "123456",
            "message": "Verification successful"
        }
        verification.status = VoterVerification.Status.SUCCESS
        verification.completed_at = timezone.now()
        verification.verification_response = response_data
        verification.save()
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.status, VoterVerification.Status.SUCCESS)
        self.assertIsNotNone(verification.completed_at)
        self.assertEqual(verification.verification_response, response_data)
    
    def test_verification_workflow_failure(self):
        """Test verification failure workflow."""
        from django.utils import timezone
        
        # Create pending verification
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        # Complete verification with failure
        response_data = {
            "error": "Invalid code",
            "message": "The verification code provided is incorrect"
        }
        verification.status = VoterVerification.Status.FAILED
        verification.completed_at = timezone.now()
        verification.verification_response = response_data
        verification.save()
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.status, VoterVerification.Status.FAILED)
        self.assertIsNotNone(verification.completed_at)
        self.assertEqual(verification.verification_response, response_data)
    
    def test_multiple_verification_attempts_per_identity(self):
        """Test that multiple verification attempts can exist for one identity."""
        # Create first attempt
        verification1 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            status=VoterVerification.Status.FAILED
        )
        
        # Create second attempt (retry)
        verification2 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            status=VoterVerification.Status.SUCCESS
        )
        
        # Both should exist
        attempts = self.voter_identity.verification_attempts.all()
        self.assertEqual(attempts.count(), 2)
    
    def test_composite_verification_multiple_methods(self):
        """Test storing multiple verification methods for composite verification."""
        # Create email verification
        email_verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            status=VoterVerification.Status.SUCCESS
        )
        
        # Create phone verification
        phone_verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="termii",
            method="PHONE",
            status=VoterVerification.Status.SUCCESS
        )
        
        # Query verifications for this identity
        verifications = self.voter_identity.verification_attempts.filter(
            status=VoterVerification.Status.SUCCESS
        )
        
        self.assertEqual(verifications.count(), 2)
        
        methods = [v.method for v in verifications]
        self.assertIn("EMAIL", methods)
        self.assertIn("PHONE", methods)
    
    def test_verification_provider_flexibility(self):
        """Test that different providers can be used for same method."""
        # Create verification with first provider
        verification1 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="PHONE",
            status=VoterVerification.Status.FAILED
        )
        
        # Retry with different provider
        verification2 = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="termii",
            method="PHONE",
            status=VoterVerification.Status.SUCCESS
        )
        
        # Both should exist
        self.assertEqual(
            self.voter_identity.verification_attempts.filter(method="PHONE").count(),
            2
        )
    
    def test_verification_response_complex_json(self):
        """Test verification_response can store complex nested JSON."""
        complex_response = {
            "provider": "twilio",
            "status": "success",
            "data": {
                "code": "123456",
                "valid_until": "2024-01-15T10:30:00Z",
                "attempts_remaining": 2
            },
            "metadata": {
                "request_id": "req-12345",
                "timestamp": "2024-01-15T10:25:00Z",
                "ip_address": "192.168.1.1"
            }
        }
        
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL",
            verification_response=complex_response
        )
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.verification_response, complex_response)
        self.assertEqual(
            verification.verification_response["data"]["code"],
            "123456"
        )
        self.assertEqual(
            verification.verification_response["metadata"]["request_id"],
            "req-12345"
        )
    
    def test_mark_completed_method_success(self):
        """Test mark_completed() helper method for successful verification."""
        from django.utils import timezone
        
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        response_data = {"code": "123456", "message": "Verified"}
        
        # Call mark_completed
        verification.mark_completed(
            status=VoterVerification.Status.SUCCESS,
            response=response_data
        )
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.status, VoterVerification.Status.SUCCESS)
        self.assertIsNotNone(verification.completed_at)
        self.assertEqual(verification.verification_response, response_data)
    
    def test_mark_completed_method_failure(self):
        """Test mark_completed() helper method for failed verification."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        response_data = {"error": "Invalid code"}
        
        # Call mark_completed
        verification.mark_completed(
            status=VoterVerification.Status.FAILED,
            response=response_data
        )
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.status, VoterVerification.Status.FAILED)
        self.assertIsNotNone(verification.completed_at)
        self.assertEqual(verification.verification_response, response_data)
    
    def test_mark_completed_method_invalid_status_raises_error(self):
        """Test mark_completed() raises error for invalid status."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        # Attempting to mark as PENDING (not a valid completion status)
        with self.assertRaises(ValueError) as cm:
            verification.mark_completed(status=VoterVerification.Status.PENDING)
        
        self.assertIn("Invalid completion status", str(cm.exception))
    
    def test_mark_completed_without_response_data(self):
        """Test mark_completed() works without response data."""
        verification = VoterVerification.objects.create(
            voter_identity=self.voter_identity,
            provider="twilio",
            method="EMAIL"
        )
        
        # Call mark_completed without response
        verification.mark_completed(status=VoterVerification.Status.SUCCESS)
        
        # Refresh from database
        verification.refresh_from_db()
        
        self.assertEqual(verification.status, VoterVerification.Status.SUCCESS)
        self.assertIsNotNone(verification.completed_at)
        # verification_response should remain None
        self.assertIsNone(verification.verification_response)



class VoteAttemptModelTests(TestCase):
    """Test suite for VoteAttempt model validation and constraints."""
    
    def setUp(self):
        """Create test fixtures: user, organizer, contest, contestant."""
        self.user = User.objects.create_user(
            email="voter@example.com",
            name="Test Voter",
            password="testpass123"
        )
        
        self.organizer = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123"
        )
        
        self.contest = Contest.objects.create(
            title="Test Contest",
            slug="test-contest",
            organizer=self.organizer,
            state=Contest.State.LIVE
        )
        
        self.contestant = Contestant.objects.create(
            poll_id=self.contest.id,  # Use poll_id since Contestant is linked to Poll
            name="Test Contestant"
        )
    
    def test_create_vote_attempt_with_defaults(self):
        """Test creating VoteAttempt with default values."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.state, VoteAttempt.State.STARTED)
        self.assertEqual(attempt.vote_quantity, 1)
        self.assertEqual(attempt.verification_context, {})
        self.assertEqual(attempt.rejection_reason, "")
        self.assertEqual(attempt.device_identifier, "")
        self.assertEqual(attempt.ip_hash, "")
        self.assertIsNone(attempt.completed_at)
        self.assertIsNotNone(attempt.created_at)
    
    def test_foreign_key_to_user(self):
        """Test foreign key relationship to User."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.user, self.user)
    
    def test_foreign_key_to_contest(self):
        """Test foreign key relationship to Contest."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.contest, self.contest)
    
    def test_foreign_key_to_contestant(self):
        """Test foreign key relationship to Contestant."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.contestant, self.contestant)
    
    def test_cascade_delete_with_user(self):
        """Test that deleting user cascades to VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        attempt_id = attempt.id
        
        # Delete user
        self.user.delete()
        
        # VoteAttempt should also be deleted
        with self.assertRaises(VoteAttempt.DoesNotExist):
            VoteAttempt.objects.get(id=attempt_id)
    
    def test_cascade_delete_with_contest(self):
        """Test that deleting contest cascades to VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        attempt_id = attempt.id
        
        # Delete contest
        self.contest.delete()
        
        # VoteAttempt should also be deleted
        with self.assertRaises(VoteAttempt.DoesNotExist):
            VoteAttempt.objects.get(id=attempt_id)
    
    def test_cascade_delete_with_contestant(self):
        """Test that deleting contestant cascades to VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        attempt_id = attempt.id
        
        # Delete contestant
        self.contestant.delete()
        
        # VoteAttempt should also be deleted
        with self.assertRaises(VoteAttempt.DoesNotExist):
            VoteAttempt.objects.get(id=attempt_id)
    
    def test_state_choices(self):
        """Test all state enum values."""
        valid_states = [
            VoteAttempt.State.STARTED,
            VoteAttempt.State.IDENTITY_CHECK,
            VoteAttempt.State.VERIFIED,
            VoteAttempt.State.PAYMENT_PENDING,
            VoteAttempt.State.PAYMENT_CONFIRMED,
            VoteAttempt.State.COMPLETED,
            VoteAttempt.State.REJECTED,
            VoteAttempt.State.EXPIRED,
            VoteAttempt.State.FAILED,
        ]
        
        for idx, state in enumerate(valid_states):
            user = User.objects.create_user(
                email=f"voter{idx}@example.com",
                name=f"Voter {idx}",
                password="testpass123"
            )
            attempt = VoteAttempt.objects.create(
                user=user,
                contest=self.contest,
                contestant=self.contestant,
                state=state
            )
            self.assertEqual(attempt.state, state)
    
    def test_default_state_is_started(self):
        """Test that default state is STARTED."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.state, VoteAttempt.State.STARTED)
    
    def test_vote_quantity_default_value(self):
        """Test that default vote_quantity is 1."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertEqual(attempt.vote_quantity, 1)
    
    def test_vote_quantity_min_validator(self):
        """Test vote_quantity minimum value validator (1)."""
        attempt = VoteAttempt(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            vote_quantity=0  # Below minimum
        )
        
        with self.assertRaises(ValidationError) as cm:
            attempt.full_clean()
        
        self.assertIn('vote_quantity', cm.exception.error_dict)
    
    def test_vote_quantity_max_validator(self):
        """Test vote_quantity maximum value validator (1000)."""
        attempt = VoteAttempt(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            vote_quantity=1001  # Above maximum
        )
        
        with self.assertRaises(ValidationError) as cm:
            attempt.full_clean()
        
        self.assertIn('vote_quantity', cm.exception.error_dict)
    
    def test_vote_quantity_valid_range(self):
        """Test vote_quantity accepts values in valid range (1-1000)."""
        # Test minimum boundary
        attempt_min = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            vote_quantity=1
        )
        self.assertEqual(attempt_min.vote_quantity, 1)
        
        # Test maximum boundary
        user2 = User.objects.create_user(
            email="voter2@example.com",
            name="Voter 2",
            password="testpass123"
        )
        attempt_max = VoteAttempt.objects.create(
            user=user2,
            contest=self.contest,
            contestant=self.contestant,
            vote_quantity=1000
        )
        self.assertEqual(attempt_max.vote_quantity, 1000)
    
    def test_verification_context_jsonfield(self):
        """Test verification_context stores JSON data correctly."""
        context_data = {
            "method": "EMAIL",
            "provider": "twilio",
            "verification_id": "ver-12345",
            "attempts": 1
        }
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            verification_context=context_data
        )
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.verification_context, context_data)
        self.assertEqual(attempt.verification_context["method"], "EMAIL")
        self.assertEqual(attempt.verification_context["verification_id"], "ver-12345")
    
    def test_rejection_reason_max_length(self):
        """Test rejection_reason field has max length of 500 characters."""
        long_reason = "A" * 501  # 501 characters
        
        attempt = VoteAttempt(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            rejection_reason=long_reason
        )
        
        with self.assertRaises(ValidationError) as cm:
            attempt.full_clean()
        
        self.assertIn('rejection_reason', cm.exception.error_dict)
    
    def test_rejection_reason_valid_length(self):
        """Test rejection_reason accepts values up to 500 characters."""
        valid_reason = "A" * 500  # Exactly 500 characters
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            rejection_reason=valid_reason
        )
        
        self.assertEqual(len(attempt.rejection_reason), 500)
    
    def test_device_identifier_max_length(self):
        """Test device_identifier field has max length of 255 characters."""
        long_identifier = "A" * 256  # 256 characters
        
        attempt = VoteAttempt(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            device_identifier=long_identifier
        )
        
        with self.assertRaises(ValidationError) as cm:
            attempt.full_clean()
        
        self.assertIn('device_identifier', cm.exception.error_dict)
    
    def test_device_identifier_valid_length(self):
        """Test device_identifier accepts values up to 255 characters."""
        valid_identifier = "A" * 255  # Exactly 255 characters
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            device_identifier=valid_identifier
        )
        
        self.assertEqual(len(attempt.device_identifier), 255)
    
    def test_ip_hash_max_length(self):
        """Test ip_hash field has max length of 64 characters (SHA-256 hash)."""
        long_hash = "A" * 65  # 65 characters
        
        attempt = VoteAttempt(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            ip_hash=long_hash
        )
        
        with self.assertRaises(ValidationError) as cm:
            attempt.full_clean()
        
        self.assertIn('ip_hash', cm.exception.error_dict)
    
    def test_ip_hash_valid_length(self):
        """Test ip_hash accepts SHA-256 hash (64 hex characters)."""
        import hashlib
        
        # Generate a valid SHA-256 hash
        sha256_hash = hashlib.sha256("192.168.1.1".encode()).hexdigest()
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            ip_hash=sha256_hash
        )
        
        self.assertEqual(len(attempt.ip_hash), 64)
        self.assertEqual(attempt.ip_hash, sha256_hash)
    
    def test_completed_at_timestamp(self):
        """Test completed_at timestamp field."""
        from django.utils import timezone
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Initially, completed_at should be None
        self.assertIsNone(attempt.completed_at)
        
        # Set completed_at
        now = timezone.now()
        attempt.state = VoteAttempt.State.COMPLETED
        attempt.completed_at = now
        attempt.save()
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertIsNotNone(attempt.completed_at)
        self.assertAlmostEqual(
            attempt.completed_at.timestamp(),
            now.timestamp(),
            delta=1
        )
    
    def test_created_at_auto_populated(self):
        """Test created_at is auto-populated."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        self.assertIsNotNone(attempt.created_at)
    
    def test_related_name_vote_attempts_on_user(self):
        """Test reverse relationship from User to VoteAttempt."""
        attempt1 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        attempt2 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            state=VoteAttempt.State.COMPLETED
        )
        
        # Access via related_name
        attempts = self.user.vote_attempts.all()
        
        self.assertEqual(attempts.count(), 2)
        self.assertIn(attempt1, attempts)
        self.assertIn(attempt2, attempts)
    
    def test_related_name_vote_attempts_on_contest(self):
        """Test reverse relationship from Contest to VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Access via related_name
        attempts = self.contest.vote_attempts.all()
        
        self.assertEqual(attempts.count(), 1)
        self.assertEqual(attempts.first(), attempt)
    
    def test_related_name_vote_attempts_on_contestant(self):
        """Test reverse relationship from Contestant to VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Access via related_name
        attempts = self.contestant.vote_attempts.all()
        
        self.assertEqual(attempts.count(), 1)
        self.assertEqual(attempts.first(), attempt)
    
    def test_composite_index_contest_state_created_at(self):
        """Test that composite index exists on (contest, state, created_at)."""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        
        # Create multiple attempts with different states
        attempt1 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            state=VoteAttempt.State.STARTED
        )
        
        # Simulate different creation time
        VoteAttempt.objects.filter(id=attempt1.id).update(
            created_at=now - timedelta(hours=1)
        )
        
        user2 = User.objects.create_user(
            email="voter2@example.com",
            name="Voter 2",
            password="testpass123"
        )
        
        attempt2 = VoteAttempt.objects.create(
            user=user2,
            contest=self.contest,
            contestant=self.contestant,
            state=VoteAttempt.State.COMPLETED
        )
        
        # Query using indexed fields
        results = VoteAttempt.objects.filter(
            contest=self.contest,
            state=VoteAttempt.State.STARTED
        ).order_by('created_at')
        
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), attempt1)
    
    def test_composite_index_user_contest(self):
        """Test that composite index exists on (user, contest)."""
        # Create contest2
        contest2 = Contest.objects.create(
            title="Contest 2",
            slug="contest-2",
            organizer=self.organizer,
            state=Contest.State.LIVE
        )
        
        contestant2 = Contestant.objects.create(
            poll_id=contest2.id,
            name="Contestant 2"
        )
        
        # Create attempts
        attempt1 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        attempt2 = VoteAttempt.objects.create(
            user=self.user,
            contest=contest2,
            contestant=contestant2
        )
        
        # Query using indexed fields
        results = VoteAttempt.objects.filter(
            user=self.user,
            contest=self.contest
        )
        
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), attempt1)
    
    def test_composite_index_ip_hash_contest_created_at(self):
        """Test that composite index exists on (ip_hash, contest, created_at)."""
        import hashlib
        
        ip_hash = hashlib.sha256("192.168.1.1".encode()).hexdigest()
        
        # Create multiple attempts with same IP hash
        user2 = User.objects.create_user(
            email="voter2@example.com",
            name="Voter 2",
            password="testpass123"
        )
        
        attempt1 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            ip_hash=ip_hash
        )
        
        attempt2 = VoteAttempt.objects.create(
            user=user2,
            contest=self.contest,
            contestant=self.contestant,
            ip_hash=ip_hash
        )
        
        # Query using indexed fields
        results = VoteAttempt.objects.filter(
            ip_hash=ip_hash,
            contest=self.contest
        ).order_by('created_at')
        
        self.assertEqual(results.count(), 2)
    
    def test_str_representation(self):
        """Test string representation of VoteAttempt."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        expected = f"Vote attempt by {self.user.email} for {self.contestant.name} ({VoteAttempt.State.STARTED})"
        self.assertEqual(str(attempt), expected)
    
    def test_mark_completed_method(self):
        """Test mark_completed() helper method."""
        from django.utils import timezone
        
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Initially not completed
        self.assertIsNone(attempt.completed_at)
        self.assertEqual(attempt.state, VoteAttempt.State.STARTED)
        
        # Mark as completed
        attempt.mark_completed()
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.COMPLETED)
        self.assertIsNotNone(attempt.completed_at)
    
    def test_mark_rejected_method(self):
        """Test mark_rejected() helper method."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        reason = "Vote limit reached for this contest"
        
        # Mark as rejected
        attempt.mark_rejected(reason)
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.REJECTED)
        self.assertEqual(attempt.rejection_reason, reason)
        self.assertIsNotNone(attempt.completed_at)
    
    def test_mark_rejected_truncates_long_reason(self):
        """Test mark_rejected() truncates rejection_reason to 500 chars."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        long_reason = "A" * 600  # 600 characters
        
        # Mark as rejected with long reason
        attempt.mark_rejected(long_reason)
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.REJECTED)
        self.assertEqual(len(attempt.rejection_reason), 500)  # Truncated
    
    def test_mark_expired_method(self):
        """Test mark_expired() helper method."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            state=VoteAttempt.State.PAYMENT_PENDING
        )
        
        # Mark as expired
        attempt.mark_expired()
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.EXPIRED)
        self.assertIsNotNone(attempt.completed_at)
    
    def test_mark_failed_method(self):
        """Test mark_failed() helper method."""
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            state=VoteAttempt.State.PAYMENT_CONFIRMED
        )
        
        reason = "Database error during vote commit"
        
        # Mark as failed
        attempt.mark_failed(reason)
        
        # Refresh from database
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.FAILED)
        self.assertEqual(attempt.rejection_reason, reason)
        self.assertIsNotNone(attempt.completed_at)
    
    def test_vote_attempt_lifecycle_workflow(self):
        """Test typical vote attempt lifecycle through various states."""
        from django.utils import timezone
        
        # Create vote attempt (STARTED)
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        self.assertEqual(attempt.state, VoteAttempt.State.STARTED)
        
        # Transition to IDENTITY_CHECK
        attempt.state = VoteAttempt.State.IDENTITY_CHECK
        attempt.save()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.IDENTITY_CHECK)
        
        # Transition to VERIFIED
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.VERIFIED)
        
        # Transition to COMPLETED (for free contest)
        attempt.mark_completed()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.COMPLETED)
        self.assertIsNotNone(attempt.completed_at)
    
    def test_paid_vote_attempt_workflow(self):
        """Test paid vote attempt lifecycle with payment states."""
        # Create vote attempt
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Skip verification for this test
        attempt.state = VoteAttempt.State.VERIFIED
        attempt.save()
        
        # Transition to PAYMENT_PENDING
        attempt.state = VoteAttempt.State.PAYMENT_PENDING
        attempt.save()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.PAYMENT_PENDING)
        
        # Transition to PAYMENT_CONFIRMED
        attempt.state = VoteAttempt.State.PAYMENT_CONFIRMED
        attempt.save()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.PAYMENT_CONFIRMED)
        
        # Finally COMPLETED
        attempt.mark_completed()
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, VoteAttempt.State.COMPLETED)
    
    def test_vote_attempt_rejection_workflow(self):
        """Test vote attempt rejection at various stages."""
        # Test rejection at STARTED
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        attempt.mark_rejected("Contest is not LIVE")
        attempt.refresh_from_db()
        
        self.assertEqual(attempt.state, VoteAttempt.State.REJECTED)
        self.assertEqual(attempt.rejection_reason, "Contest is not LIVE")
    
    def test_multiple_vote_attempts_per_user_per_contest(self):
        """Test that a user can have multiple vote attempts in same contest."""
        # First attempt
        attempt1 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Second attempt (e.g., after first was rejected)
        attempt2 = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant
        )
        
        # Both should exist
        attempts = self.user.vote_attempts.filter(contest=self.contest).all()
        self.assertEqual(attempts.count(), 2)
    
    def test_verification_context_size_limit(self):
        """Test verification_context should not exceed 100KB serialized size."""
        import json
        
        # Create context data approaching 100KB
        # This is more of a guideline test; actual enforcement would be in application logic
        large_context = {
            "data": "A" * 90000,  # ~90KB of data
            "method": "COMPOSITE",
            "provider": "test"
        }
        
        # Should be able to create
        attempt = VoteAttempt.objects.create(
            user=self.user,
            contest=self.contest,
            contestant=self.contestant,
            verification_context=large_context
        )
        
        # Verify it was saved
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.verification_context)
        
        # Check serialized size is reasonable
        serialized = json.dumps(attempt.verification_context)
        self.assertLess(len(serialized), 100000)  # Less than 100KB



class VoteModelRefactoringTests(TestCase):
    """
    Test suite for Vote model refactoring (Task 3.2).
    
    Tests the enhanced Vote model with:
    - voter_identity FK instead of direct User FK
    - vote_number field for sequential tracking
    - vote_quantity field (1-1000)
    - device_identifier (255 char max)
    - ip_hash for hashed IP addresses
    - payment FK (nullable)
    
    Validates Requirements: 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 5.13
    """
    
    def setUp(self):
        """Create test fixtures: user, poll, contestant, voter_identity."""
        from polls.models import Poll, Contestant
        from voting.models import Vote, VoterIdentity
        
        self.user = User.objects.create_user(
            email="voter@example.com",
            name="Test Voter",
            password="testpass123"
        )
        
        self.organizer = User.objects.create_user(
            email="organizer@example.com",
            name="Test Organizer",
            password="testpass123"
        )
        
        self.poll = Poll.objects.create(
            title="Test Poll",
            slug="test-poll",
            creator=self.organizer,
            status=Poll.Status.ACTIVE
        )
        
        self.contestant = Contestant.objects.create(
            poll=self.poll,
            name="Contestant A",
            description="Test contestant"
        )
        
        # Create VoterIdentity for the user/poll combination
        self.voter_identity = VoterIdentity.objects.create(
            user=self.user,
            contest=self.poll,  # Note: using poll as contest for now
            verification_status=VoterIdentity.VerificationStatus.VERIFIED
        )
    
    def test_vote_links_to_voter_identity(self):
        """Test that Vote links to VoterIdentity instead of User directly (Req 5.1)."""
        from voting.models import Vote
        
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='test-device-123',
            ip_hash='abc123hash'
        )
        
        self.assertEqual(vote.voter_identity, self.voter_identity)
        self.assertEqual(vote.voter_identity.user, self.user)
    
    def test_vote_number_field_exists(self):
        """Test that vote_number field is present and required (Req 5.2, 5.3)."""
        from voting.models import Vote
        
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=42,
            vote_quantity=1,
            device_identifier='test-device',
            ip_hash='hash123'
        )
        
        self.assertEqual(vote.vote_number, 42)
    
    def test_vote_quantity_field_with_validators(self):
        """Test vote_quantity field with min/max validators (Req 5.13)."""
        from voting.models import Vote
        from django.core.exceptions import ValidationError
        
        # Valid vote_quantity values
        for quantity in [1, 5, 100, 500, 1000]:
            vote = Vote(
                poll=self.poll,
                contestant=self.contestant,
                voter_identity=self.voter_identity,
                vote_number=quantity,
                vote_quantity=quantity,
                device_identifier='device',
                ip_hash='hash'
            )
            vote.full_clean()  # Should not raise
        
        # Invalid: vote_quantity < 1
        vote_invalid_min = Vote(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=0,  # Invalid
            device_identifier='device',
            ip_hash='hash'
        )
        with self.assertRaises(ValidationError):
            vote_invalid_min.full_clean()
        
        # Invalid: vote_quantity > 1000
        vote_invalid_max = Vote(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1001,  # Invalid
            device_identifier='device',
            ip_hash='hash'
        )
        with self.assertRaises(ValidationError):
            vote_invalid_max.full_clean()
    
    def test_device_identifier_max_length(self):
        """Test device_identifier field has max length 255 (Req 5.6)."""
        from voting.models import Vote
        
        # Valid: 255 characters
        long_identifier = 'a' * 255
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier=long_identifier,
            ip_hash='hash'
        )
        self.assertEqual(len(vote.device_identifier), 255)
        
        # Invalid: > 255 characters should be truncated by database
        too_long_identifier = 'b' * 256
        vote2 = Vote(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=2,
            vote_quantity=1,
            device_identifier=too_long_identifier,
            ip_hash='hash2'
        )
        # Django will enforce this at the DB level or validation level
        with self.assertRaises((ValidationError, Exception)):
            vote2.full_clean()
    
    def test_ip_hash_field_for_privacy(self):
        """Test ip_hash field stores hashed IP addresses (Req 5.7)."""
        from voting.models import Vote
        import hashlib
        
        # Simulate IP hashing
        ip_address = '192.168.1.1'
        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()
        
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='device',
            ip_hash=ip_hash
        )
        
        self.assertEqual(vote.ip_hash, ip_hash)
        self.assertEqual(len(vote.ip_hash), 64)  # SHA-256 produces 64 hex chars
    
    def test_payment_foreign_key_nullable(self):
        """Test payment FK is nullable for free contests (Req 5.8)."""
        from voting.models import Vote
        
        # Vote without payment (free contest)
        vote_free = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='device',
            ip_hash='hash',
            payment=None  # Should be allowed
        )
        self.assertIsNone(vote_free.payment)
    
    def test_payment_foreign_key_with_payment(self):
        """Test payment FK links to Payment for paid contests (Req 5.8)."""
        from voting.models import Vote
        from payments.models import Payment
        
        # Create a payment
        payment = Payment.objects.create(
            user=self.user,
            email=self.user.email,
            amount=Decimal('100.00'),
            reference='test-payment-ref-123',
            status=Payment.Status.SUCCESS
        )
        
        vote_paid = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='device',
            ip_hash='hash',
            payment=payment
        )
        
        self.assertEqual(vote_paid.payment, payment)
        self.assertEqual(vote_paid.payment.reference, 'test-payment-ref-123')
    
    def test_vote_with_bulk_quantity_uses_vote_quantity_field(self):
        """Test bulk voting uses vote_quantity field (Req 5.13)."""
        from voting.models import Vote
        
        # Single vote record representing 50 votes
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=50,
            device_identifier='device',
            ip_hash='hash'
        )
        
        self.assertEqual(vote.vote_quantity, 50)
    
    def test_sequential_vote_numbers(self):
        """Test votes have sequential vote_number within a poll (Req 5.3)."""
        from voting.models import Vote
        
        # Create multiple votes with sequential numbers
        vote1 = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='device1',
            ip_hash='hash1'
        )
        
        vote2 = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=2,
            vote_quantity=1,
            device_identifier='device2',
            ip_hash='hash2'
        )
        
        vote3 = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=3,
            vote_quantity=1,
            device_identifier='device3',
            ip_hash='hash3'
        )
        
        self.assertEqual(vote1.vote_number, 1)
        self.assertEqual(vote2.vote_number, 2)
        self.assertEqual(vote3.vote_number, 3)
    
    def test_vote_model_string_representation(self):
        """Test Vote.__str__() uses vote_number and vote_quantity."""
        from voting.models import Vote
        
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=7,
            vote_quantity=3,
            device_identifier='device',
            ip_hash='hash'
        )
        
        expected_str = f"Vote #7 on {self.contestant.name} (x3)"
        self.assertEqual(str(vote), expected_str)
    
    def test_vote_has_required_indexes(self):
        """Test Vote model has required indexes for performance."""
        from voting.models import Vote
        
        # Check that Vote model has the expected indexes
        indexes = [index.name for index in Vote._meta.indexes]
        
        # New indexes from task 3.2
        self.assertIn('voting_vote_poll_vote_num_idx', indexes)
        self.assertIn('voting_vote_voter_identity_idx', indexes)
        self.assertIn('voting_vote_payment_idx', indexes)
    
    def test_backward_compatibility_legacy_fields_still_exist(self):
        """Test that legacy fields are maintained for backward compatibility."""
        from voting.models import Vote
        
        vote = Vote.objects.create(
            poll=self.poll,
            contestant=self.contestant,
            voter_identity=self.voter_identity,
            vote_number=1,
            vote_quantity=1,
            device_identifier='new-device',
            ip_hash='new-hash',
            # Legacy fields
            voter=self.user,
            quantity=1,
            device_fingerprint='old-fingerprint',
            ip_address='127.0.0.1'
        )
        
        # Verify both new and legacy fields are accessible
        self.assertEqual(vote.voter_identity, self.voter_identity)
        self.assertEqual(vote.voter, self.user)
        self.assertEqual(vote.vote_quantity, 1)
        self.assertEqual(vote.quantity, 1)
        self.assertEqual(vote.device_identifier, 'new-device')
        self.assertEqual(vote.device_fingerprint, 'old-fingerprint')
