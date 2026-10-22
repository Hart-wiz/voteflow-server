"""
Django admin configuration for the custom User model.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import OrganizerProfile

User = get_user_model()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "name", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "name")
    ordering = ("-created_at",)

    # Override fieldsets since we don't use `username`
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("name", "avatar_url")}),
        ("Permissions", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "name", "password1", "password2", "role"),
        }),
    )


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "user", "is_approved", "requested_at", "approved_at")
    list_filter = ("is_approved", "is_verified")
    search_fields = ("business_name", "user__email", "user__name")
    readonly_fields = ("requested_at", "approved_at")
