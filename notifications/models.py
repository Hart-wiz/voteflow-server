import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Status(models.TextChoices):
        READ = "read", "Read"
        DELIVERED = "delivered", "Delivered"

    # Primary Key Definition
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="The user this notification was sent to",
    )

    title = models.CharField(max_length=30)
    description = models.TextField(blank=True, max_length=2000, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DELIVERED,
        db_index=True,
    )
    email = models.EmailField()

    # Automated Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Sorts newest notifications first by default
        ordering = ("-created_at",)

        # Performance Indexing
        indexes = (
            models.Index(fields=["receiver", "status"]),
            models.Index(fields=["receiver", "email", "status"]),
            models.Index(fields=["title"]),
        )

    def __str__(self):
        return f"Notification({self.title} -> {self.receiver})"
