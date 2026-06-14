from django.conf import settings
from django.db import models

# Create your models here.

class Vote(models.Model):
    poll = models.ForeignKey(
        "polls.Poll",
        on_delete=models.CASCADE,
        related_name="votes"
    )

    contestant = models.ForeignKey(
        "contestants.Contestant",
        on_delete=models.CASCADE,
        related_name="votes"
    )

    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes"
    )

    # for anonymous or paid voters who don't create accounts
    voter_identifier = models.CharField(max_length=255, blank=True, null=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)

    is_paid = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["poll", "contestant"]),
            models.Index(fields=["voter"]),
        ]

    def __str__(self):
        return f"Vote on {self.contestant.name}"


# Add Fraud signals
device_fingerprint = models.CharField(max_length=255, blank=True, null=True)

is_suspicious = models.BooleanField(default=False)


# Create Vote Audit Log (Very Important)
class VoteAuditLog(models.Model):
    ACTIONS = (
        ("vote_attempt", "Vote Attempt"),
        ("vote_success", "Vote Success"),
        ("vote_blocked", "Vote Blocked"),
    )

    poll = models.ForeignKey("polls.Poll", on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)

    action = models.CharField(max_length=20, choices=ACTIONS)

    created_at = models.DateTimeField(auto_now_add=True)