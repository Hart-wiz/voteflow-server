"""
Custom User model for VoteFlow.

Uses UUID primary keys and email-based authentication.
Roles: 'user' (default), 'creator' (can create polls), 'admin' (superuser).

Frontend expects:  { id, name, email, avatarUrl, role, createdAt }
"""

import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    """
    Custom manager that uses email as the unique identifier
    instead of Django's default username.
    """

    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        extra_fields.setdefault("role", "user")
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")
        return self.create_user(email, name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User with UUID PK and role-based access.

    Fields serialized to frontend:
        id          → UUID
        name        → display name
        email       → unique login identifier
        avatar_url  → optional profile picture URL  (camelCase: avatarUrl)
        role        → 'user' | 'creator' | 'admin'
        created_at  → auto timestamp  (camelCase: createdAt)
    """

    class Role(models.TextChoices):
        USER = "user", "User"
        CREATOR = "creator", "Creator"
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    avatar_url = models.URLField(blank=True, null=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)

    # Django auth plumbing
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return self.email