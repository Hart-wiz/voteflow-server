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
from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    Record of a Paystack payment initialization.
    Used to track payment flow from init → webhook confirmation.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    email = models.EmailField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=255, unique=True, db_index=True)
    processed = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.reference} ({self.status})"


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

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    lifetime_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)

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
        max_length=20, choices=Type.choices,
    )

    # Optional metadata (bank details for withdrawals, payment ref for earnings)
    metadata = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["type"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.type} {self.amount} ({self.status})"