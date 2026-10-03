"""
Custom User model for VoteFlow.

Uses UUID primary keys and email-based authentication.
Roles: 'user' (default), 'organiser' (can create polls from the poll model ), 'admin' (superuser).

Frontend expects:  { id, name, email, avatarUrl, role, createdAt }
"""

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager["User"]):
    """
    Custom manager that uses email as the unique identifier
    instead of Django's default username.
    """

    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        if not password:
            raise ValueError("Password is required")
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, name, password, **extra_fields)


if TYPE_CHECKING:
    from accounts.models import OrganizerProfile


class User(AbstractBaseUser, PermissionsMixin):
    """Core Identity & Auth Model only."""

    class Role(models.TextChoices):
        USER = "USER", "User"
        ORGANIZER = "ORGANIZER", "Organizer"
        ADMIN = "ADMIN", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    avatar_url = models.URLField(blank=True, null=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.USER, db_index=True
    )

    # Core Flags
    is_active = models.BooleanField(default=True)
    is_email_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["name"]

    objects: UserManager = UserManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    # class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
    #     indexes = (
    #         models.Index(fields=["email"]),
    #         models.Index(fields=["role"]),
    #     )
    # already handled when creating them

    if TYPE_CHECKING:
        organizer_profile = OrganizerProfile

    def __str__(self):
        return self.email


class UserOTP(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="otp_profile"
    )
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_valid(self):
        """Checks if the OTP is less than 10 minutes old."""

        return timezone.now() < self.created_at + timedelta(minutes=10)


class OrganizerProfile(models.Model):
    """Profile for users with organizer privileges."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="organizer_profile",
    )
    payout_account_id = models.CharField(max_length=255, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    is_approved = models.BooleanField(default=False, db_index=True)
    is_verified = models.BooleanField(default=False)

    # Business information
    business_name = models.CharField(max_length=255, blank=True, default="")
    business_registration_number = models.CharField(
        max_length=100, blank=True, default=""
    )

    # Approval workflow
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_organizers",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_organizerprofile"
        indexes = (models.Index(fields=["is_approved", "created_at"]),)

    def __str__(self):
        return f"OrganizerProfile for {self.user.email}"
