"""
Payment and wallet models for VoteFlow.

Models:
    Payment      — Paystack payment records (for initializing transactions)
    Wallet       — User's wallet with balance tracking
    Transaction  — All financial activity (earnings, withdrawals, refunds)

The former WalletTransaction and Withdrawal models are unified into Transaction.
Frontend wallet response expects:
    { availableBalance, pendingEarnings, lifetimeEarnings, transactions }
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    Enhanced payment record with vote attempt linking.

    Tracks payment flow from init → webhook confirmation with support for
    vote attempt linking, provider reference tracking, and organizer earnings
    calculation.

    Requirements: 7.1, 7.3, 7.5, 7.9, 7.10, 7.12, 7.13
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # NEW: Link to VoteAttempt with CASCADE delete
    vote_attempt = models.ForeignKey(
        "voting.VoteAttempt",
        on_delete=models.CASCADE,
        related_name="payments",
        null=True,
        blank=True,
        help_text="The vote attempt this payment is associated with",
    )

    # NEW: Provider reference with unique constraint
    provider_reference = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Unique reference from payment provider (e.g., Paystack)",
    )

    # LEGACY: Keep old reference field for backward compatibility
    reference = models.CharField(
        max_length=255,
        unique=True,
        blank=True,
        null=True,
        help_text="[LEGACY] Use provider_reference instead",
    )

    # Enhanced status with new values
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # NEW: Total amount and organizer earnings
    total_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total payment amount (vote_quantity × price_per_vote)",
    )

    organizer_earnings = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amount credited to organizer after revenue share calculation",
    )

    # NEW: Currency field (ISO 4217)
    currency = models.CharField(
        max_length=3,
        default="NGN",
        help_text="ISO 4217 currency code (e.g., NGN, USD, EUR)",
    )

    # LEGACY: Keep old fields for backward compatibility
    email = models.EmailField(blank=True, default="")
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="[LEGACY] Use total_amount instead",
    )
    processed = models.BooleanField(default=False)

    # Enhanced metadata and timestamps
    metadata = models.JSONField(
        null=True,
        blank=True,
        help_text="Provider-specific response data and additional context",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # NEW: Confirmation timestamp
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when payment was confirmed",
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"Payment {self.provider_reference} ({self.status})"


class Wallet(models.Model):
    """
    User's wallet. Created automatically via signal on user registration.

    Fields:
        balance           — available for withdrawal
        pending_earnings  — earnings not yet settled
        lifetime_earnings — total earnings ever (never decreases)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
    )

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0))
    pending_earnings = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal(0)
    )
    lifetime_earnings = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal(0)
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} Wallet (₦{self.balance})"


class Transaction(models.Model):
    """
    Unified financial transaction record.

    Replaces the old WalletTransaction and Withdrawal models.
    Frontend expects:
        { id, date, description, amount, status, type }

    amount is signed:
        + for credits (earnings, refunds)
        - for debits (withdrawals)
    """

    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        PENDING = "pending", "Pending"
        FAILED = "failed", "Failed"

    class Type(models.TextChoices):
        EARNING = "earning", "Earning"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        REFUND = "refund", "Refund"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="transactions",
    )

    description = models.CharField(max_length=500, blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.COMPLETED
    )
    type = models.CharField(
        max_length=20,
        choices=Type.choices,
    )

    # Optional metadata (bank details for withdrawals, payment ref for earnings)
    metadata = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["type"]),
            models.Index(fields=["status"]),
        )

    def __str__(self):
        return f"{self.type} {self.amount} ({self.status})"
