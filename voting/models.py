"""
Voting models.

Vote       — individual vote record (audit trail, source of truth)
VoteAuditLog — security/anti-fraud logging for all vote attempts

The Vote model is the source of truth; Contestant.votes is a denormalized
counter updated atomically for read performance.
"""

import uuid
from django.conf import settings
from django.db import models


class Vote(models.Model):
    """
    An individual vote cast for a contestant in a poll.

    For paid polls, payment_ref links to the verified Paystack transaction.
    voter_email captures the email for anonymous/non-authenticated voters.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    poll = models.ForeignKey(
        "polls.Poll",
        on_delete=models.CASCADE,
        related_name="votes",
    )

    contestant = models.ForeignKey(
        "polls.Contestant",
        on_delete=models.CASCADE,
        related_name="vote_records",
    )

    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes",
    )

    voter_email = models.EmailField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    payment_ref = models.CharField(max_length=255, blank=True, default="")

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    is_paid = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Anti-fraud fields
    device_fingerprint = models.CharField(max_length=255, blank=True, default="")
    is_suspicious = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "contestant"]),
            models.Index(fields=["voter"]),
            models.Index(fields=["payment_ref"]),
        ]

    def __str__(self):
        return f"Vote on {self.contestant.name} (x{self.quantity})"


class VoteAuditLog(models.Model):
    """
    Security audit log for every vote attempt.
    Captures IP, user agent, and action outcome for fraud analysis.
    """

    ACTIONS = (
        ("vote_attempt", "Vote Attempt"),
        ("vote_success", "Vote Success"),
        ("vote_blocked", "Vote Blocked"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    poll = models.ForeignKey("polls.Poll", on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    action = models.CharField(max_length=20, choices=ACTIONS)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "action"]),
            models.Index(fields=["ip_address"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.poll} @ {self.ip_address}"