"""
Models for the polls app.

Contains both Poll and Contestant (merged from the former contestants app).
The frontend treats contestants as nested children of a poll.

Frontend expects Poll:
    { id, slug, title, organizer, category, description, image, status,
      endsAt, isPaid, pricePerVote, tags, votesCount, contestants: [...] }

Frontend expects Contestant:
    { id, name, author, description, image, votes }
"""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.conf import settings

# from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from .validators import validate_iana_timezone

if TYPE_CHECKING:
    # Tell type checkers about reverse manager relations
    from django.db.models.manager import RelatedManager

    from .models import Contestant, ContestantMedia


class Poll(models.Model):
    """
    A voting poll created by a user with role 'creator' or 'admin'.

    Key design decisions:
    - `slug` is the public identifier used in URLs (not the UUID).
    - `status` drives frontend display logic; auto-slug generation prevents collisions.
    - `tags` uses JSONField (list of strings) for MVP simplicity.<
    - `votes_count` is a denormalized aggregate for fast list queries.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ENDING_SOON = "ending_soon", "Ending Soon"
        CLOSED = "closed", "Closed"
        DRAFT = "draft", "Draft"
        NEW = "new", "New"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="polls",
        help_text="The user who created this poll.",
    )

    creator_id: uuid.UUID
    if TYPE_CHECKING:
        contestants: RelatedManager[Contestant]

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=300, blank=True)
    organizer = models.CharField(
        max_length=255,
        blank=True,
        help_text="Display name of the organizer. Defaults to creator.name on save.",
    )
    category = models.CharField(max_length=100, blank=True, default="")
    description = models.TextField(blank=True, default="")
    image = models.ImageField(upload_to="polls/", blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )

    ends_at = models.DateTimeField(null=True, blank=True)

    is_paid = models.BooleanField(default=False)
    price_per_vote = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal(0), blank=True
    )

    tags = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=["slug"]),
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
            models.Index(fields=["creator"]),
        )

    def save(self, *args, **kwargs):
        # Auto-generate slug from title if not set
        if not self.slug and self.title:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Poll.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Default organizer to creator's name
        if not self.organizer and self.creator_id:
            self.organizer = self.creator.name

        super().save(*args, **kwargs)

    @property
    def votes_count(self):
        """
        Total votes across all contestants.
        For list views, prefer annotating this in the queryset instead.
        """
        return self.contestants.aggregate(total=models.Sum("votes"))["total"] or 0

    def __str__(self):
        return self.title


class Contest(models.Model):
    """
    A voting contest with lifecycle state management.
    Renamed from Poll to reflect industry-standard terminology.

    This model implements comprehensive state management, timezone-aware scheduling,
    and configurable results visibility for production-grade voting applications.
    """

    class State(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SCHEDULED = "SCHEDULED", "Scheduled"
        LIVE = "LIVE", "Live"
        PAUSED = "PAUSED", "Paused"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"
        ARCHIVED = "ARCHIVED", "Archived"
        SUSPENDED = "SUSPENDED", "Suspended"

    class ResultsVisibility(models.TextChoices):
        AFTER_CLOSE = "after_close", "After Close"
        REAL_TIME = "real_time", "Real Time"
        NEVER = "never", "Never"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True, max_length=300)

    # Ownership
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contests",
        help_text="The user who created and manages this contest.",
    )
    source_poll = models.OneToOneField(
        Poll,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contest_record",
        help_text="Legacy poll used to preserve contestant and vote records during migration.",
    )

    # Content
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="")
    image = models.ImageField(upload_to="contests/", blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)

    # Lifecycle
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.DRAFT,
        help_text="Current lifecycle state of the contest.",
    )

    # Timezone-aware scheduling
    timezone = models.CharField(
        max_length=50,
        default="UTC",
        validators=[validate_iana_timezone],
        help_text="IANA timezone identifier (e.g., 'America/New_York')",
    )
    start_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the contest is scheduled to start (timezone-aware).",
    )
    end_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the contest is scheduled to end (timezone-aware).",
    )

    # State timestamps
    published_at = models.DateTimeField(
        null=True, blank=True, help_text="When the contest transitioned to LIVE state."
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the contest transitioned to CLOSED state.",
    )

    # Results visibility
    results_visibility = models.CharField(
        max_length=20,
        choices=ResultsVisibility.choices,
        default=ResultsVisibility.AFTER_CLOSE,
        help_text="Controls when results can be viewed by users.",
    )

    # Optimistic locking for state transitions
    version = models.PositiveIntegerField(
        default=0,
        help_text="Version number for optimistic locking during state transitions.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at"]
        indexes: ClassVar[list] = [
            models.Index(fields=["state", "start_time"]),
            models.Index(fields=["state", "end_time"]),
            models.Index(fields=["organizer", "state"]),
            models.Index(fields=["category"]),
        ]
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=(models.Q(end_time__gt=models.F("start_time"))),
                name="valid_time_range",
            )
        ]

    def save(self, *args, **kwargs):
        """Auto-generate slug from title if not set."""
        if not self.slug and self.title:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Contest.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.state})"


class Contestant(models.Model):
    """
    A contestant (option / candidate) within a poll.

    `votes` is a denormalized integer counter, updated atomically via F()
    expressions when votes are cast. This avoids expensive COUNT queries
    on the Vote table for every poll list request.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    poll = models.ForeignKey(
        Poll,
        on_delete=models.CASCADE,
        related_name="contestants",
    )

    if TYPE_CHECKING:
        media: RelatedManager[ContestantMedia]

    name = models.CharField(max_length=255)
    author = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    image = models.ImageField(upload_to="contestants/", blank=True, null=True)

    votes = models.PositiveIntegerField(
        default=0,
        help_text="Denormalized vote count. Updated atomically via F() on each vote.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-votes",)
        indexes = (models.Index(fields=["poll"]),)

    def __str__(self):
        return f"{self.name} ({self.poll.title})"


class ContestantMedia(models.Model):
    """
    Media files (images and videos) associated with a contestant.

    Allows organizers to enrich contestant profiles with multiple media items.
    Files are stored externally (e.g., Cloudinary) with URLs stored in the database.

    Requirements:
    - Supports IMAGE and VIDEO media types
    - Maximum 10 media items per contestant
    - Files up to 10MB
    - Ordered display via display_order field
    """

    class MediaType(models.TextChoices):
        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Video"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    contestant = models.ForeignKey(
        Contestant,
        on_delete=models.CASCADE,
        related_name="media",
        help_text="The contestant this media belongs to.",
    )

    media_type = models.CharField(
        max_length=10,
        choices=MediaType.choices,
        help_text="Type of media file (IMAGE or VIDEO).",
    )

    file_url = models.URLField(
        max_length=2048,
        help_text="URL of the media file (e.g., Cloudinary URL).",
    )

    caption = models.TextField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional caption describing the media.",
    )

    display_order = models.IntegerField(
        default=0,
        help_text="Order in which media should be displayed (ascending).",
    )

    file_size_bytes = models.PositiveIntegerField(
        help_text="Size of the file in bytes. Maximum 10MB (10485760 bytes).",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "polls_contestantmedia"
        ordering = ["display_order"]
        indexes: ClassVar[list] = [
            models.Index(fields=["contestant", "display_order"]),
        ]
        constraints: ClassVar[list] = [
            models.CheckConstraint(
                condition=models.Q(file_size_bytes__lte=10485760),
                name="max_file_size_10mb",
            )
        ]

    def __str__(self):
        return f"{self.media_type} for {self.contestant.name}"


class Livestream(models.Model):
    """
    Optional livestream associated with a contest.

    Allows organizers to add real-time video streaming to their contests,
    enabling viewers to watch live events while participating in voting.

    Requirements:
    - One livestream per contest (OneToOne relationship)
    - Three status states: SCHEDULED, LIVE, ENDED
    - Tracks viewer count during active streams
    - Records timing information (scheduled, actual start, end times)
    """

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        LIVE = "LIVE", "Live"
        ENDED = "ENDED", "Ended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    contest = models.OneToOneField(
        Contest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="livestream",
        help_text="The contest this livestream is associated with.",
    )

    stream_url = models.URLField(
        max_length=2048,
        help_text="URL of the livestream (e.g., YouTube, Twitch, custom RTMP endpoint).",
    )

    stream_key = models.CharField(
        max_length=255,
        help_text="Private streaming key for the provider.",
    )

    provider = models.CharField(
        max_length=100,
        help_text="Livestream provider (e.g., 'youtube', 'twitch', 'custom').",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        help_text="Current status of the livestream.",
    )

    scheduled_start_time = models.DateTimeField(
        help_text="When the livestream is scheduled to start (timezone-aware).",
    )

    actual_start_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the livestream actually started (set when status → LIVE).",
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the livestream ended (set when status → ENDED).",
    )

    viewer_count = models.PositiveIntegerField(
        default=0,
        help_text="Current number of viewers watching the livestream.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "polls_livestream"
        indexes: ClassVar[list] = [
            models.Index(fields=["contest", "status"]),
        ]

    def __str__(self):
        contest_title = self.contest.title if self.contest else "No Contest"
        return f"Livestream for {contest_title} ({self.status})"
