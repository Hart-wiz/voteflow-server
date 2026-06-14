
from django.conf import settings
from django.db import models
from django.utils.text import slugify

# Create your models here.

class Poll(models.Model):
    class VoteType(models.TextChoices):
        FREE = "free", "Free"
        PAID = "paid", "Paid"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="polls"
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    slug = models.SlugField(unique=True, blank=True)

    vote_type = models.CharField(
        max_length=10,
        choices=VoteType.choices,
        default=VoteType.FREE
    )

    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1

            while Poll.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return self.title