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
from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Poll(models.Model):
    """
    A voting poll created by a user with role 'creator' or 'admin'.

    Key design decisions:
    - `slug` is the public identifier used in URLs (not the UUID).
    - `status` drives frontend display logic; auto-slug generation prevents collisions.
    - `tags` uses JSONField (list of strings) for MVP simplicity.
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
        max_digits=10, decimal_places=2, default=0, blank=True
    )

    tags = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
            models.Index(fields=["creator"]),
        ]

    def save(self, *args, **kwargs):
        # Auto-generate slug from title if not set
        if not self.slug:
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
        ordering = ["-votes"]
        indexes = [
            models.Index(fields=["poll"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.poll.title})"