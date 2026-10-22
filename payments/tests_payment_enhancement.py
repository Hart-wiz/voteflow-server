"""
Unit tests for Payment model enhancements (Task 4.1).

Tests verify:
- FK to VoteAttempt with CASCADE delete
- provider_reference unique constraint and index
- status enum (PENDING, CONFIRMED, FAILED, REFUNDED)
- total_amount and organizer_earnings decimal fields
- currency field (3 char max, default NGN)
- metadata JSONField
- confirmed_at timestamp

Requirements: 7.1, 7.3, 7.5, 7.9, 7.10, 7.12, 7.13
"""

import pytest
from decimal import Decimal
from django.db import IntegrityError
from django.utils import timezone
from accounts.models import User
from polls.models import Poll, Contestant, Contest
from voting.models import VoteAttempt
from payments.models import Payment


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create(
        email="testuser@example.com",
        name="Test User",
    )


@pytest.fixture
def organizer(db):
    """Create an organizer user."""
    return User.objects.create(
        email="organizer@example.com",
        name="Organizer",
        role="ORGANIZER",
    )


@pytest.fixture
def poll(db, organizer):
    """Create a test poll."""
    return Poll.objects.create(
        title="Test Poll",
        slug="test-poll",
        creator=organizer,
        price_per_vote=Decimal("100.00"),
    )


@pytest.fixture
def contest(db, organizer):
    """Create a test contest."""
    return Contest.objects.create(
        title="Test Contest",
        slug="test-contest",
        organizer=organizer,
    )


@pytest.fixture
def contestant(db, poll):
    """Create a test contestant."""
    return Contestant.objects.create(
        poll=poll,
        name="Contestant 1",
    )


@pytest.fixture
def vote_attempt(db, user, contest, contestant):
    """Create a test vote attempt."""
    return VoteAttempt.objects.create(
        user=user,
        contest=contest,
        contestant=contestant,
        vote_quantity=2,
    )


@pytest.mark.django_db
class TestPaymentEnhancements:
    """Test suite for Payment model enhancements (Task 4.1)."""

    def test_payment_has_vote_attempt_fk(self, user, vote_attempt):
        """Verify Payment links to VoteAttempt via FK."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_test_001",
            total_amount=Decimal("200.00"),
        )
        
        assert payment.vote_attempt == vote_attempt
        assert payment.vote_attempt.id == vote_attempt.id

    def test_vote_attempt_cascade_delete(self, user, vote_attempt):
        """Verify CASCADE delete behavior when VoteAttempt is deleted."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_test_002",
            total_amount=Decimal("200.00"),
        )
        payment_id = payment.id
        
        # Delete the vote attempt
        vote_attempt.delete()
        
        # Payment should be deleted too (CASCADE)
        assert not Payment.objects.filter(id=payment_id).exists()

    def test_provider_reference_unique_constraint(self, user, vote_attempt):
        """Verify provider_reference has unique constraint."""
        Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_unique_001",
            total_amount=Decimal("100.00"),
        )
        
        # Attempting to create another payment with same reference should fail
        with pytest.raises(IntegrityError):
            Payment.objects.create(
                user=user,
                vote_attempt=vote_attempt,
                provider_reference="ref_unique_001",
                total_amount=Decimal("100.00"),
            )

    def test_status_enum_values(self, user, vote_attempt):
        """Verify status field accepts all enum values."""
        statuses = ["PENDING", "CONFIRMED", "FAILED", "REFUNDED"]
        
        for idx, status in enumerate(statuses):
            payment = Payment.objects.create(
                user=user,
                vote_attempt=vote_attempt,
                provider_reference=f"ref_status_{idx}",
                total_amount=Decimal("100.00"),
                status=status,
            )
            assert payment.status == status

    def test_total_amount_decimal_field(self, user, vote_attempt):
        """Verify total_amount stores decimal values correctly."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_amount_001",
            total_amount=Decimal("12345.67"),
        )
        
        payment.refresh_from_db()
        assert payment.total_amount == Decimal("12345.67")

    def test_organizer_earnings_decimal_field(self, user, vote_attempt):
        """Verify organizer_earnings stores decimal values correctly."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_earnings_001",
            total_amount=Decimal("100.00"),
            organizer_earnings=Decimal("80.00"),
        )
        
        payment.refresh_from_db()
        assert payment.organizer_earnings == Decimal("80.00")

    def test_currency_field_default_ngn(self, user, vote_attempt):
        """Verify currency field defaults to NGN."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_currency_001",
            total_amount=Decimal("100.00"),
        )
        
        assert payment.currency == "NGN"

    def test_currency_field_max_length(self, user, vote_attempt):
        """Verify currency field accepts 3-character codes."""
        currencies = ["NGN", "USD", "EUR", "GBP"]
        
        for idx, currency in enumerate(currencies):
            payment = Payment.objects.create(
                user=user,
                vote_attempt=vote_attempt,
                provider_reference=f"ref_curr_{idx}",
                total_amount=Decimal("100.00"),
                currency=currency,
            )
            assert payment.currency == currency

    def test_metadata_json_field(self, user, vote_attempt):
        """Verify metadata stores JSON data correctly."""
        metadata = {
            "provider": "paystack",
            "transaction_id": "12345",
            "customer_code": "CUS_abc123",
        }
        
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_metadata_001",
            total_amount=Decimal("100.00"),
            metadata=metadata,
        )
        
        payment.refresh_from_db()
        assert payment.metadata == metadata
        assert payment.metadata["provider"] == "paystack"

    def test_confirmed_at_timestamp(self, user, vote_attempt):
        """Verify confirmed_at timestamp is nullable and stores datetime."""
        # Create payment without confirmed_at
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_confirmed_001",
            total_amount=Decimal("100.00"),
            status="PENDING",
        )
        
        assert payment.confirmed_at is None
        
        # Update to CONFIRMED with timestamp
        confirmed_time = timezone.now()
        payment.status = "CONFIRMED"
        payment.confirmed_at = confirmed_time
        payment.save()
        
        payment.refresh_from_db()
        assert payment.status == "CONFIRMED"
        assert payment.confirmed_at is not None

    def test_payment_string_representation(self, user, vote_attempt):
        """Verify __str__ method uses provider_reference and status."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_str_001",
            total_amount=Decimal("100.00"),
            status="PENDING",
        )
        
        assert str(payment) == "Payment ref_str_001 (PENDING)"

    def test_backward_compatibility_fields(self, user, vote_attempt):
        """Verify legacy fields are still present for backward compatibility."""
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_legacy_001",
            reference="legacy_ref_001",
            total_amount=Decimal("100.00"),
            amount=Decimal("100.00"),
            email="test@example.com",
            processed=True,
        )
        
        # Verify legacy fields exist and work
        assert payment.reference == "legacy_ref_001"
        assert payment.amount == Decimal("100.00")
        assert payment.email == "test@example.com"
        assert payment.processed is True

    def test_decimal_precision(self, user, vote_attempt):
        """Verify decimal fields have correct precision (8 digits, 2 decimal places)."""
        # Max value: 999999.99
        payment = Payment.objects.create(
            user=user,
            vote_attempt=vote_attempt,
            provider_reference="ref_precision_001",
            total_amount=Decimal("999999.99"),
            organizer_earnings=Decimal("799999.99"),
        )
        
        payment.refresh_from_db()
        assert payment.total_amount == Decimal("999999.99")
        assert payment.organizer_earnings == Decimal("799999.99")

    def test_payment_indexes_exist(self, db):
        """Verify indexes are created on payment model."""
        from django.db import connection
        
        # Get indexes for the payment table
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'payments_payment'
            """)
            indexes = [row[0] for row in cursor.fetchall()]
        
        # Check for provider_reference index
        assert any('provide' in idx.lower() for idx in indexes)
        
        # Check for user_status composite index
        assert any('user' in idx.lower() and 'st' in idx.lower() for idx in indexes)
        
        # Check for vote_attempt index
        assert any('vote' in idx.lower() for idx in indexes)
