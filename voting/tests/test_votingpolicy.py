"""
Unit tests for VotingPolicy model.

Tests CHECK constraints, field validators, and model validation logic
for the VotingPolicy model including vote limits, verification requirements,
and pricing configuration.

Validates Requirements: 3.3, 3.4, 3.6, 3.7, 3.10, 3.11
"""

import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from accounts.models import User
from polls.models import Contest
from voting.models import VotingPolicy


@pytest.fixture
def user():
    """Create a test user for contest creation."""
    return User.objects.create_user(
        email="organizer@example.com",
        password="testpass123",
        name="Test Organizer"
    )


@pytest.fixture
def contest(user):
    """Create a test contest for VotingPolicy creation."""
    return Contest.objects.create(
        title="Test Contest",
        slug="test-contest",
        organizer=user,
        state=Contest.State.DRAFT
    )


@pytest.mark.django_db
class TestVotingPolicyConstraints:
    """Tests for VotingPolicy model database constraints."""

    def test_max_votes_required_for_limited_constraint_valid(self, contest):
        """
        Test CHECK constraint allows LIMITED vote_limit_type with max_votes_per_voter set.
        Validates Requirement 3.3, 3.4
        """
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=5,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        
        assert policy.vote_limit_type == VotingPolicy.VoteLimitType.LIMITED
        assert policy.max_votes_per_voter == 5

    def test_max_votes_required_for_limited_constraint_violation(self, contest):
        """
        Test CHECK constraint rejects LIMITED vote_limit_type without max_votes_per_voter.
        Validates Requirement 3.3, 3.4
        """
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VotingPolicy.objects.create(
                    contest=contest,
                    vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
                    max_votes_per_voter=None,  # Should violate constraint
                    verification_method=VotingPolicy.VerificationMethod.NONE,
                    price_per_vote=Decimal("0.00"),
                    revenue_share_percentage=80
                )
        
        assert "max_votes_required_for_limited" in str(exc_info.value)

    def test_max_votes_null_for_one_vote_limit(self, contest):
        """
        Test CHECK constraint allows ONE vote_limit_type with null max_votes_per_voter.
        Validates Requirement 3.4
        """
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.ONE,
            max_votes_per_voter=None,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        
        assert policy.vote_limit_type == VotingPolicy.VoteLimitType.ONE
        assert policy.max_votes_per_voter is None

    def test_max_votes_null_for_unlimited_vote_limit(self, contest):
        """
        Test CHECK constraint allows UNLIMITED vote_limit_type with null max_votes_per_voter.
        Validates Requirement 3.4
        """
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            max_votes_per_voter=None,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        
        assert policy.vote_limit_type == VotingPolicy.VoteLimitType.UNLIMITED
        assert policy.max_votes_per_voter is None

    def test_max_votes_set_for_one_vote_limit_violation(self, contest):
        """
        Test CHECK constraint rejects ONE vote_limit_type with max_votes_per_voter set.
        Validates Requirement 3.4
        """
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VotingPolicy.objects.create(
                    contest=contest,
                    vote_limit_type=VotingPolicy.VoteLimitType.ONE,
                    max_votes_per_voter=5,  # Should violate constraint
                    verification_method=VotingPolicy.VerificationMethod.NONE,
                    price_per_vote=Decimal("0.00"),
                    revenue_share_percentage=80
                )
        
        assert "max_votes_required_for_limited" in str(exc_info.value)

    def test_max_votes_set_for_unlimited_vote_limit_violation(self, contest):
        """
        Test CHECK constraint rejects UNLIMITED vote_limit_type with max_votes_per_voter set.
        Validates Requirement 3.4
        """
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VotingPolicy.objects.create(
                    contest=contest,
                    vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
                    max_votes_per_voter=10,  # Should violate constraint
                    verification_method=VotingPolicy.VerificationMethod.NONE,
                    price_per_vote=Decimal("0.00"),
                    revenue_share_percentage=80
                )
        
        assert "max_votes_required_for_limited" in str(exc_info.value)

    def test_composite_requires_methods_constraint_valid(self, contest):
        """
        Test CHECK constraint allows COMPOSITE verification_method with required_verification_methods set.
        Validates Requirement 3.6, 3.7
        """
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=["EMAIL", "PHONE"],
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        
        assert policy.verification_method == VotingPolicy.VerificationMethod.COMPOSITE
        assert policy.required_verification_methods == ["EMAIL", "PHONE"]

    def test_composite_requires_methods_constraint_violation(self, contest):
        """
        Test CHECK constraint rejects COMPOSITE verification_method without required_verification_methods.
        Validates Requirement 3.6, 3.7
        """
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VotingPolicy.objects.create(
                    contest=contest,
                    vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
                    verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
                    required_verification_methods=None,  # Should violate constraint
                    price_per_vote=Decimal("0.00"),
                    revenue_share_percentage=80
                )
        
        assert "composite_requires_methods" in str(exc_info.value)

    def test_required_verification_methods_null_for_non_composite(self, contest):
        """
        Test CHECK constraint allows non-COMPOSITE verification methods with null required_verification_methods.
        Validates Requirement 3.7
        """
        non_composite_methods = [
            VotingPolicy.VerificationMethod.EMAIL,
            VotingPolicy.VerificationMethod.PHONE,
            VotingPolicy.VerificationMethod.NIN,
            VotingPolicy.VerificationMethod.VOTERS_CARD,
            VotingPolicy.VerificationMethod.FINGERPRINT,
            VotingPolicy.VerificationMethod.NONE,
        ]
        
        for method in non_composite_methods:
            policy = VotingPolicy.objects.create(
                contest=Contest.objects.create(
                    title=f"Test Contest {method}",
                    slug=f"test-contest-{method}",
                    organizer=contest.organizer,
                    state=Contest.State.DRAFT
                ),
                vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
                verification_method=method,
                required_verification_methods=None,
                price_per_vote=Decimal("0.00"),
                revenue_share_percentage=80
            )
            
            assert policy.verification_method == method
            assert policy.required_verification_methods is None

    def test_required_verification_methods_set_for_non_composite_violation(self, contest):
        """
        Test CHECK constraint rejects non-COMPOSITE verification methods with required_verification_methods set.
        Validates Requirement 3.7
        """
        with pytest.raises(IntegrityError) as exc_info:
            with transaction.atomic():
                VotingPolicy.objects.create(
                    contest=contest,
                    vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
                    verification_method=VotingPolicy.VerificationMethod.EMAIL,
                    required_verification_methods=["EMAIL"],  # Should violate constraint
                    price_per_vote=Decimal("0.00"),
                    revenue_share_percentage=80
                )
        
        assert "composite_requires_methods" in str(exc_info.value)


@pytest.mark.django_db
class TestVotingPolicyFieldValidators:
    """Tests for VotingPolicy field validators."""

    def test_max_votes_per_voter_minimum_value(self, contest):
        """
        Test max_votes_per_voter validator rejects values below 2.
        Validates Requirement 3.3
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1,  # Below minimum
            verification_method=VotingPolicy.VerificationMethod.NONE
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "max_votes_per_voter" in exc_info.value.error_dict
        assert "Ensure this value is greater than or equal to 2" in str(exc_info.value)

    def test_max_votes_per_voter_maximum_value(self, contest):
        """
        Test max_votes_per_voter validator rejects values above 1000.
        Validates Requirement 3.3
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1001,  # Above maximum
            verification_method=VotingPolicy.VerificationMethod.NONE
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "max_votes_per_voter" in exc_info.value.error_dict
        assert "Ensure this value is less than or equal to 1000" in str(exc_info.value)

    def test_max_votes_per_voter_valid_boundary_values(self, contest):
        """
        Test max_votes_per_voter validator accepts boundary values 2 and 1000.
        Validates Requirement 3.3
        """
        # Test minimum boundary (2)
        policy_min = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=2,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        assert policy_min.max_votes_per_voter == 2
        
        # Test maximum boundary (1000)
        contest2 = Contest.objects.create(
            title="Test Contest 2",
            slug="test-contest-2",
            organizer=contest.organizer,
            state=Contest.State.DRAFT
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=1000,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        assert policy_max.max_votes_per_voter == 1000

    def test_price_per_vote_minimum_value(self, contest):
        """
        Test price_per_vote validator rejects negative values.
        Validates Requirement 3.10
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("-0.01")  # Below minimum
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "price_per_vote" in exc_info.value.error_dict
        assert "Ensure this value is greater than or equal to 0" in str(exc_info.value)

    def test_price_per_vote_maximum_value(self, contest):
        """
        Test price_per_vote validator rejects values above 999999.99.
        Validates Requirement 3.10
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("1000000.00")  # Above maximum
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "price_per_vote" in exc_info.value.error_dict
        assert "Ensure this value is less than or equal to 999999.99" in str(exc_info.value)

    def test_price_per_vote_valid_boundary_values(self, contest):
        """
        Test price_per_vote validator accepts boundary values 0.00 and 999999.99.
        Validates Requirement 3.10
        """
        # Test minimum boundary (0.00)
        policy_min = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=80
        )
        assert policy_min.price_per_vote == Decimal("0.00")
        
        # Test maximum boundary (999999.99)
        contest2 = Contest.objects.create(
            title="Test Contest 2",
            slug="test-contest-2",
            organizer=contest.organizer,
            state=Contest.State.DRAFT
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("999999.99"),
            revenue_share_percentage=80
        )
        assert policy_max.price_per_vote == Decimal("999999.99")

    def test_price_per_vote_decimal_precision(self, contest):
        """
        Test price_per_vote stores values with precision 8 and scale 2.
        Validates Requirement 3.10
        """
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("12345.67"),
            revenue_share_percentage=80
        )
        
        assert policy.price_per_vote == Decimal("12345.67")
        # Verify it's stored with 2 decimal places
        assert str(policy.price_per_vote) == "12345.67"

    def test_revenue_share_percentage_minimum_value(self, contest):
        """
        Test revenue_share_percentage validator rejects values below 0.
        Validates Requirement 3.11
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=-1  # Below minimum
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "revenue_share_percentage" in exc_info.value.error_dict
        assert "Ensure this value is greater than or equal to 0" in str(exc_info.value)

    def test_revenue_share_percentage_maximum_value(self, contest):
        """
        Test revenue_share_percentage validator rejects values above 100.
        Validates Requirement 3.11
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=101  # Above maximum
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.full_clean()
        
        assert "revenue_share_percentage" in exc_info.value.error_dict
        assert "Ensure this value is less than or equal to 100" in str(exc_info.value)

    def test_revenue_share_percentage_valid_boundary_values(self, contest):
        """
        Test revenue_share_percentage validator accepts boundary values 0 and 100.
        Validates Requirement 3.11
        """
        # Test minimum boundary (0)
        policy_min = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=0
        )
        assert policy_min.revenue_share_percentage == 0
        
        # Test maximum boundary (100)
        contest2 = Contest.objects.create(
            title="Test Contest 2",
            slug="test-contest-2",
            organizer=contest.organizer,
            state=Contest.State.DRAFT
        )
        policy_max = VotingPolicy.objects.create(
            contest=contest2,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.NONE,
            price_per_vote=Decimal("0.00"),
            revenue_share_percentage=100
        )
        assert policy_max.revenue_share_percentage == 100


@pytest.mark.django_db
class TestVotingPolicyModelValidation:
    """Tests for VotingPolicy model clean() method validation."""

    def test_clean_method_validates_limited_requires_max_votes(self, contest):
        """
        Test clean() method validates LIMITED vote_limit_type requires max_votes_per_voter.
        Validates Requirement 3.3, 3.4
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.LIMITED,
            max_votes_per_voter=None,
            verification_method=VotingPolicy.VerificationMethod.NONE
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "max_votes_per_voter" in exc_info.value.error_dict
        assert "required when vote_limit_type is LIMITED" in str(exc_info.value)

    def test_clean_method_validates_one_excludes_max_votes(self, contest):
        """
        Test clean() method validates ONE vote_limit_type must not have max_votes_per_voter.
        Validates Requirement 3.4
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.ONE,
            max_votes_per_voter=5,
            verification_method=VotingPolicy.VerificationMethod.NONE
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "max_votes_per_voter" in exc_info.value.error_dict
        assert "must be NULL when vote_limit_type is ONE or UNLIMITED" in str(exc_info.value)

    def test_clean_method_validates_unlimited_excludes_max_votes(self, contest):
        """
        Test clean() method validates UNLIMITED vote_limit_type must not have max_votes_per_voter.
        Validates Requirement 3.4
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            max_votes_per_voter=10,
            verification_method=VotingPolicy.VerificationMethod.NONE
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "max_votes_per_voter" in exc_info.value.error_dict
        assert "must be NULL when vote_limit_type is ONE or UNLIMITED" in str(exc_info.value)

    def test_clean_method_validates_composite_requires_methods(self, contest):
        """
        Test clean() method validates COMPOSITE verification requires required_verification_methods.
        Validates Requirement 3.6, 3.7
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=None
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "required when verification_method is COMPOSITE" in str(exc_info.value)

    def test_clean_method_validates_composite_methods_is_list(self, contest):
        """
        Test clean() method validates required_verification_methods must be a list.
        Validates Requirement 3.7
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods="EMAIL"  # String instead of list
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "must be a list" in str(exc_info.value)

    def test_clean_method_validates_composite_requires_at_least_two_methods(self, contest):
        """
        Test clean() method validates COMPOSITE requires at least 2 verification methods.
        Validates Requirement 3.6
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=["EMAIL"]  # Only one method
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "at least 2 distinct methods" in str(exc_info.value)

    def test_clean_method_validates_composite_methods_are_distinct(self, contest):
        """
        Test clean() method validates all verification methods must be distinct.
        Validates Requirement 3.6
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=["EMAIL", "EMAIL"]  # Duplicate
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "must be distinct" in str(exc_info.value)

    def test_clean_method_validates_composite_methods_are_valid(self, contest):
        """
        Test clean() method validates all verification methods are valid choices.
        Validates Requirement 3.7
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.COMPOSITE,
            required_verification_methods=["EMAIL", "INVALID_METHOD"]
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "Invalid verification method" in str(exc_info.value)

    def test_clean_method_validates_non_composite_excludes_methods(self, contest):
        """
        Test clean() method validates non-COMPOSITE must not have required_verification_methods.
        Validates Requirement 3.7
        """
        policy = VotingPolicy(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED,
            verification_method=VotingPolicy.VerificationMethod.EMAIL,
            required_verification_methods=["EMAIL"]
        )
        
        with pytest.raises(ValidationError) as exc_info:
            policy.clean()
        
        assert "required_verification_methods" in exc_info.value.error_dict
        assert "must be NULL when verification_method is not COMPOSITE" in str(exc_info.value)


@pytest.mark.django_db
class TestVotingPolicyDefaults:
    """Tests for VotingPolicy default values and basic functionality."""

    def test_default_values(self, contest):
        """Test that default values are set correctly on creation."""
        policy = VotingPolicy.objects.create(contest=contest)
        
        assert policy.vote_limit_type == VotingPolicy.VoteLimitType.UNLIMITED
        assert policy.max_votes_per_voter is None
        assert policy.verification_method == VotingPolicy.VerificationMethod.NONE
        assert policy.required_verification_methods is None
        assert policy.price_per_vote == Decimal("0.00")
        assert policy.revenue_share_percentage == 80
        assert policy.allow_anonymous is False

    def test_one_to_one_relationship_with_contest(self, contest):
        """Test OneToOne relationship with Contest model."""
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED
        )
        
        # Access from policy to contest
        assert policy.contest == contest
        
        # Access from contest to policy
        assert contest.voting_policy == policy

    def test_cascade_delete_with_contest(self, contest):
        """Test that VotingPolicy is deleted when Contest is deleted."""
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED
        )
        policy_id = policy.id
        
        # Delete contest
        contest.delete()
        
        # Policy should be deleted too
        assert not VotingPolicy.objects.filter(id=policy_id).exists()

    def test_str_representation(self, contest):
        """Test string representation of VotingPolicy."""
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED
        )
        
        str_repr = str(policy)
        assert "Voting Policy for" in str_repr
        assert contest.title in str_repr

    def test_timestamps_auto_set(self, contest):
        """Test that created_at and updated_at timestamps are auto-set."""
        from django.utils import timezone
        
        before = timezone.now()
        policy = VotingPolicy.objects.create(
            contest=contest,
            vote_limit_type=VotingPolicy.VoteLimitType.UNLIMITED
        )
        after = timezone.now()
        
        assert before <= policy.created_at <= after
        assert before <= policy.updated_at <= after
