"""
Voting models.

Vote       — individual vote record (audit trail, source of truth)
VoteAuditLog — security/anti-fraud logging for all vote attempts
VotingPolicy — configurable voting rules for a contest

The Vote model is the source of truth; Contestant.votes is a denormalized
counter updated atomically for read performance.
"""

import uuid
from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class VotingPolicy(models.Model):
    """
    Configurable voting rules for a contest.

    Defines vote limits, verification requirements, pricing, and anonymity settings.
    Each contest has exactly one VotingPolicy via OneToOne relationship.
    """

    class VoteLimitType(models.TextChoices):
        ONE = "ONE", "One Vote"
        LIMITED = "LIMITED", "Limited Votes"
        UNLIMITED = "UNLIMITED", "Unlimited Votes"

    class VerificationMethod(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        PHONE = "PHONE", "Phone"
        NIN = "NIN", "National ID Number"
        VOTERS_CARD = "VOTERS_CARD", "Voter's Card"
        FINGERPRINT = "FINGERPRINT", "Fingerprint"
        COMPOSITE = "COMPOSITE", "Multiple Methods"
        NONE = "NONE", "No Verification"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    contest = models.OneToOneField(
        "polls.Contest",
        on_delete=models.CASCADE,
        related_name="voting_policy",
        help_text="The contest this voting policy applies to.",
    )

    # Vote limits
    vote_limit_type = models.CharField(
        max_length=20,
        choices=VoteLimitType.choices,
        default=VoteLimitType.UNLIMITED,
        help_text="Type of vote limit for this contest.",
    )

    max_votes_per_voter = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(2), MaxValueValidator(1000)],
        help_text="Maximum votes per voter (required when vote_limit_type is LIMITED).",
    )

    # Verification
    verification_method = models.CharField(
        max_length=20,
        choices=VerificationMethod.choices,
        default=VerificationMethod.NONE,
        help_text="Identity verification method required for voters.",
    )

    required_verification_methods = models.JSONField(
        null=True,
        blank=True,
        help_text="Array of verification methods for COMPOSITE type (e.g., ['EMAIL', 'PHONE']).",
    )

    # Pricing
    price_per_vote = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("999999.99")),
        ],
        help_text="Price per individual vote in the contest currency.",
    )

    revenue_share_percentage = models.IntegerField(
        default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage of revenue that goes to organizer (0-100).",
    )

    # Privacy
    allow_anonymous = models.BooleanField(
        default=False,
        help_text="Whether anonymous (non-authenticated) voting is permitted.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "voting_votingpolicy"
        verbose_name = "Voting Policy"
        verbose_name_plural = "Voting Policies"
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        vote_limit_type="LIMITED", max_votes_per_voter__isnull=False
                    )
                    | models.Q(
                        vote_limit_type__in=["ONE", "UNLIMITED"],
                        max_votes_per_voter__isnull=True,
                    )
                ),
                name="max_votes_required_for_limited",
                violation_error_message="max_votes_per_voter is required when vote_limit_type is LIMITED.",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        verification_method="COMPOSITE",
                        required_verification_methods__isnull=False,
                    )
                    | models.Q(
                        verification_method__in=[
                            "EMAIL",
                            "PHONE",
                            "NIN",
                            "VOTERS_CARD",
                            "FINGERPRINT",
                            "NONE",
                        ],
                        required_verification_methods__isnull=True,
                    )
                ),
                name="composite_requires_methods",
                violation_error_message="required_verification_methods is required when verification_method is COMPOSITE.",
            ),
        ]

    def __str__(self):
        return f"Voting Policy for {self.contest.title}"

    def clean(self):
        """Additional validation for complex constraints."""
        from django.core.exceptions import ValidationError

        # Validate vote limit type and max votes consistency
        if (
            self.vote_limit_type == self.VoteLimitType.LIMITED
            and not self.max_votes_per_voter
        ):
            raise ValidationError(
                {
                    "max_votes_per_voter": "This field is required when vote_limit_type is LIMITED."
                }
            )

        if (
            self.vote_limit_type
            in [
                self.VoteLimitType.ONE,
                self.VoteLimitType.UNLIMITED,
            ]
            and self.max_votes_per_voter is not None
        ):
            raise ValidationError(
                {
                    "max_votes_per_voter": "This field must be NULL when vote_limit_type is ONE or UNLIMITED."
                }
            )

        # Validate verification method and required methods consistencyF
        if self.verification_method == self.VerificationMethod.COMPOSITE:
            if not self.required_verification_methods:
                raise ValidationError(
                    {
                        "required_verification_methods": "This field is required when verification_method is COMPOSITE."
                    }
                )

            if not isinstance(self.required_verification_methods, list):
                raise ValidationError(
                    {
                        "required_verification_methods": "This field must be a list of verification method strings."
                    }
                )

            if len(self.required_verification_methods) < 2:
                raise ValidationError(
                    {
                        "required_verification_methods": "COMPOSITE verification requires at least 2 distinct methods."
                    }
                )

            # Check for distinct values
            if len(self.required_verification_methods) != len(
                set(self.required_verification_methods)
            ):
                raise ValidationError(
                    {
                        "required_verification_methods": "All verification methods must be distinct."
                    }
                )

            # Validate that all methods are valid choices
            valid_methods = [
                self.VerificationMethod.EMAIL,
                self.VerificationMethod.PHONE,
                self.VerificationMethod.NIN,
                self.VerificationMethod.VOTERS_CARD,
                self.VerificationMethod.FINGERPRINT,
            ]

            if self.required_verification_methods:
                methods = (
                    [self.required_verification_methods]
                    if isinstance(self.required_verification_methods, str)
                    else self.required_verification_methods
                )
                for method in methods:
                    if method not in valid_methods:
                        raise ValidationError(
                            {
                                "required_verification_methods": f"Invalid verification method: {method}. Must be one of {valid_methods}."
                            }
                        )

        elif self.required_verification_methods is not None:
            raise ValidationError(
                {
                    "required_verification_methods": "This field must be NULL when verification_method is not COMPOSITE."
                }
            )


class VoterIdentity(models.Model):
    """
    Contest-scoped verified identity for a voter.

    Each user can have one VoterIdentity per contest, enabling per-contest
    verification requirements and tracking verification status separately
    for each contest a voter participates in.
    """

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Unverified"
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        EXPIRED = "EXPIRED", "Expired"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="voter_identities",
        help_text="The user whose identity is being verified.",
    )

    contest = models.ForeignKey(
        "polls.Contest",
        on_delete=models.CASCADE,
        related_name="voter_identities",
        help_text="The contest for which this identity verification applies.",
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
        # db_index=True, covered by composite
        help_text="Current status of identity verification for this contest.",
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when identity verification was completed successfully.",
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional expiration timestamp for time-limited verification methods.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Voter Identity"
        verbose_name_plural = "Voter Identities"
        constraints: ClassVar[list] = [
            models.UniqueConstraint(
                fields=["user", "contest"], name="unique_voter_identity_per_contest"
            )
        ]
        indexes: ClassVar[list] = [
            models.Index(fields=["contest", "verification_status"]),
            models.Index(fields=["user", "contest"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.contest.title} ({self.verification_status})"

    def mark_verified(self, save=True):
        """Marks the identity as verified and updates the timestamp."""
        self.verification_status = self.VerificationStatus.VERIFIED
        if not self.verified_at:
            self.verified_at = timezone.now()

        if save:
            self.save(
                update_fields=["verification_status", "verified_at", "updated_at"]
            )


class VoterVerification(models.Model):
    """
    Individual verification attempt record.

    Tracks each verification attempt for a voter identity, storing provider-specific
    details and verification outcomes. Multiple verification attempts may exist
    per VoterIdentity, especially for COMPOSITE verification methods.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    voter_identity = models.ForeignKey(
        "VoterIdentity",
        on_delete=models.CASCADE,
        related_name="verification_attempts",
        help_text="The voter identity being verified.",
    )

    provider = models.CharField(
        max_length=100,
        help_text="Name of the verification provider (e.g., 'twilio', 'termii', 'smile_identity').",
    )

    method = models.CharField(
        max_length=20,
        help_text="Verification method used (EMAIL, PHONE, NIN, VOTERS_CARD, FINGERPRINT).",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Status of this verification attempt.",
    )

    verification_response = models.JSONField(
        null=True,
        blank=True,
        help_text="Provider-specific response data (stored as JSON).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when verification was completed (success or failed).",
    )

    class Meta:
        db_table = "voting_voterverification"
        verbose_name = "Voter Verification"
        verbose_name_plural = "Voter Verifications"
        indexes: ClassVar[list] = [
            models.Index(fields=["voter_identity", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.method} verification via {self.provider} - {self.status}"

    def mark_completed(self, status: str, response: dict | None = None, save=True):
        """Mark verification as completed with success or failure status."""
        if status not in [self.Status.SUCCESS, self.Status.FAILED]:
            raise ValueError(f"Invalid completion status: {status}")

        self.status = status
        self.completed_at = timezone.now()
        if response:
            self.verification_response = response

        if save:
            self.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "verification_response",
                ]
            )


class VoteAttempt(models.Model):
    """
    Tracking for vote attempts with state machine.

    Tracks the entire lifecycle of a voting attempt from initiation through
    identity verification, payment processing, and final vote commitment.
    Used for security analysis, fraud detection, and audit trails.
    """

    class State(models.TextChoices):
        STARTED = "STARTED", "Started"
        IDENTITY_CHECK = "IDENTITY_CHECK", "Identity Check"
        VERIFIED = "VERIFIED", "Verified"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Payment Pending"
        PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Payment Confirmed"
        COMPLETED = "COMPLETED", "Completed"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vote_attempts",
        help_text="The user attempting to vote.",
    )

    contest = models.ForeignKey(
        "polls.Contest",
        on_delete=models.CASCADE,
        related_name="vote_attempts",
        help_text="The contest being voted in.",
    )

    contestant = models.ForeignKey(
        "polls.Contestant",
        on_delete=models.CASCADE,
        related_name="vote_attempts",
        help_text="The contestant receiving the vote.",
    )

    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.STARTED,
        help_text="Current state in the vote attempt lifecycle.",
    )

    vote_quantity = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Number of votes being cast in this attempt (1-1000).",
    )

    # Context and security
    verification_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Verification-related context data (max 100KB serialized).",
    )

    rejection_reason = models.TextField(
        max_length=500,
        blank=True,
        default="",
        help_text="Reason for rejection if state transitions to REJECTED.",
    )

    device_identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Device fingerprint or identifier for fraud detection.",
    )

    ip_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 hash of the IP address for privacy and security.",
    )

    created_at = models.DateTimeField(
        auto_now_add=True, help_text="When the vote attempt was initiated."
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the vote attempt reached a terminal state (COMPLETED, REJECTED, EXPIRED, FAILED).",
    )

    class Meta:
        db_table = "voting_voteattempt"
        verbose_name = "Vote Attempt"
        verbose_name_plural = "Vote Attempts"
        indexes: ClassVar[list] = [
            models.Index(fields=["contest", "state", "created_at"]),
            models.Index(fields=["user", "contest"]),
            models.Index(fields=["ip_hash", "contest", "created_at"]),
        ]
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(vote_quantity__gte=1, vote_quantity__lte=1000),
                name="vote_attempt_quantity_range",
            ),
        ]

    def __str__(self):
        return f"Vote attempt by {self.user.email} for {self.contestant.name} ({self.state})"

    def mark_completed(self, save=True):
        """Mark the vote attempt as completed and set the completion timestamp."""
        self.state = self.State.COMPLETED
        if not self.completed_at:
            self.completed_at = timezone.now()

        if save:
            self.save(update_fields=["state", "completed_at"])

    def mark_rejected(self, reason: str, save=True):
        """Mark the vote attempt as rejected with a reason."""
        self.state = self.State.REJECTED
        self.rejection_reason = reason[:500]  # Enforce max length
        if not self.completed_at:
            self.completed_at = timezone.now()

        if save:
            self.save(update_fields=["state", "rejection_reason", "completed_at"])

    def mark_expired(self, save=True):
        """Mark the vote attempt as expired."""
        self.state = self.State.EXPIRED
        if not self.completed_at:
            self.completed_at = timezone.now()

        if save:
            self.save(update_fields=["state", "completed_at"])

    def mark_failed(self, reason: str = "", save=True):
        """Mark the vote attempt as failed."""
        self.state = self.State.FAILED
        if reason:
            self.rejection_reason = reason[:500]
        if not self.completed_at:
            self.completed_at = timezone.now()

        if save:
            self.save(update_fields=["state", "rejection_reason", "completed_at"])


class Vote(models.Model):
    """
    Enhanced immutable vote record - source of truth for vote counts.

    Key changes from original Vote model:
    - Links to VoterIdentity instead of User directly (enables per-contest verification)
    - Includes vote_number for sequential tracking within contests
    - Includes vote_quantity to support bulk voting (1-1000 votes per record)
    - Uses ip_hash instead of raw IP for privacy
    - Links to Payment for paid contests
    - Maintains backward compatibility with legacy fields during transition

    Once created, votes should not be modified or deleted (enforced via DB triggers).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Contest and contestant references
    poll = models.ForeignKey(
        "polls.Poll",
        on_delete=models.CASCADE,
        related_name="votes",
        help_text="The poll this vote belongs to",
    )

    contestant = models.ForeignKey(
        "polls.Contestant",
        on_delete=models.CASCADE,
        related_name="vote_records",
        help_text="The contestant receiving this vote",
    )

    # NEW: Voter identity reference (replaces direct User FK)
    voter_identity = models.ForeignKey(
        "VoterIdentity",
        on_delete=models.RESTRICT,
        related_name="votes",
        null=True,
        blank=True,
        help_text="The verified voter identity for this vote",
    )

    # LEGACY: Keep old voter FK for backward compatibility during migration
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes",
        help_text="[LEGACY] Direct user reference - use voter_identity instead",
    )

    # NEW: Sequential vote tracking
    vote_number = models.IntegerField(
        validators=[MinValueValidator(1)],
        help_text="Sequential number within the contest"
    )

    # NEW: Vote quantity (supports bulk voting)
    vote_quantity = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Number of votes in this record (1-1000)",
    )

    # LEGACY: Keep old quantity field for backward compatibility
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="[LEGACY] Use vote_quantity instead"
    )

    # NEW: Payment link for paid contests
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="votes",
        help_text="Payment record for paid contests",
    )

    # LEGACY: Keep old payment_ref for backward compatibility
    payment_ref = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="[LEGACY] Use payment FK instead"
    )

    # Security and fraud detection
    # NEW: Consolidated device identifier (replaces device_fingerprint)
    device_identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Device fingerprint or identifier for fraud detection",
    )

    # LEGACY: Keep old device_fingerprint for backward compatibility
    device_fingerprint = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="[LEGACY] Use device_identifier instead"
    )

    # NEW: Hashed IP for privacy
    ip_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 hash of the IP address for privacy and security",
    )

    # LEGACY: Keep old IP address field during migration
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="[LEGACY] Use ip_hash instead"
    )

    # LEGACY: Email for anonymous voters (kept for backward compatibility)
    voter_email = models.EmailField(
        blank=True,
        default="",
        help_text="[LEGACY] Email for anonymous voters"
    )

    # Additional fields
    user_agent = models.TextField(blank=True, default="")
    is_paid = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0))
    is_suspicious = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = (
            # Legacy indexes
            models.Index(fields=["poll", "contestant"]),
            # NEW indexes for enhanced tracking
            models.Index(fields=["poll", "voter_identity"], name="voting_vote_poll_voter_idx"),
            models.Index(fields=["created_at"], name="voting_vote_created_at_idx"),
        )
        constraints = (
            models.UniqueConstraint(
                fields=["poll", "vote_number"], name="unique_poll_vote_number"
            ),
            models.CheckConstraint(
                condition=models.Q(vote_quantity__gte=1, vote_quantity__lte=1000),
                name="vote_quantity_range",
            ),
        )

    def __str__(self):
        return f"Vote #{self.vote_number} on {self.contestant.name} (x{self.vote_quantity})"


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
        indexes = (
            models.Index(fields=["poll", "action"]),
            models.Index(fields=["ip_address"]),
        )

    def __str__(self):
        return f"{self.action} on {self.poll} @ {self.ip_address}"


class AuditLog(models.Model):
    """
    Comprehensive audit logging for security analysis.

    Tracks all security-relevant actions including authentication, authorization,
    voting attempts, contest management, and payment transactions. Provides
    a complete audit trail for fraud detection and compliance.

    Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.18
    """

    class ActionType(models.TextChoices):
        VOTE_STARTED = "VOTE_STARTED", "Vote Started"
        VOTE_COMPLETED = "VOTE_COMPLETED", "Vote Completed"
        VOTE_REJECTED = "VOTE_REJECTED", "Vote Rejected"
        VOTE_FAILED = "VOTE_FAILED", "Vote Failed"
        LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login Success"
        LOGIN_FAILED = "LOGIN_FAILED", "Login Failed"
        LOGOUT = "LOGOUT", "Logout"
        ROLE_CHANGE = "ROLE_CHANGE", "Role Change"
        CONTEST_CREATED = "CONTEST_CREATED", "Contest Created"
        CONTEST_STATE_CHANGE = "CONTEST_STATE_CHANGE", "Contest State Change"
        PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Payment Confirmed"
        PAYMENT_FAILED = "PAYMENT_FAILED", "Payment Failed"
        SUSPICIOUS_PATTERN = "SUSPICIOUS_PATTERN", "Suspicious Pattern"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # User reference (nullable - some actions may not have a user)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
        related_name="audit_logs",
        help_text="The user who performed the action (null for system actions).",
    )

    # Action details
    action_type = models.CharField(
        max_length=30,
        choices=ActionType.choices,
        db_index=False,
        help_text="Type of action being audited.",
    )

    # Resource tracking
    resource_type = models.CharField(
        max_length=100,
        help_text="Type of resource affected (e.g., 'Contest', 'Vote', 'Payment').",
    )

    resource_id = models.CharField(
        max_length=255,
        help_text="Identifier of the affected resource.",
    )

    # Timestamp with millisecond precision
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=False,
        help_text="When the action occurred (with millisecond precision).",
    )

    # Security tracking
    device_fingerprint = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Device fingerprint for fraud detection (max 512 characters).",
    )

    ip_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA-256 hash of the IP address for privacy and security.",
    )

    # Contextual data
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional contextual information about the action (stored as JSON).",
    )

    class Meta:
        db_table = "voting_auditlog"
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes: ClassVar[list] = [
            models.Index(fields=["timestamp"], name="auditlog_timestamp_idx"),
            models.Index(fields=["user", "timestamp"], name="auditlog_user_timestamp_idx"),
            models.Index(fields=["action_type", "timestamp"], name="auditlog_action_timestamp_idx"),
            models.Index(fields=["resource_type", "resource_id"], name="auditlog_resource_idx"),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        user_str = self.user.email if self.user else "System"
        return f"{self.action_type} by {user_str} at {self.timestamp}"
