"""
Admin configuration for the voting app.
"""

from django.contrib import admin

from .models import (
    Vote,
    VoteAttempt,
    VoteAuditLog,
    VoterIdentity,
    VoterVerification,
    VotingPolicy,
)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = (
        "contestant",
        "poll",
        "quantity",
        "is_paid",
        "voter_email",
        "created_at",
    )
    list_filter = ("is_paid", "poll")
    search_fields = ("voter_email", "payment_ref")
    readonly_fields = ("id", "created_at")


@admin.register(VoteAuditLog)
class VoteAuditLogAdmin(admin.ModelAdmin):
    list_display = ("poll", "action", "ip_address", "created_at")
    list_filter = ("action",)
    readonly_fields = ("id", "created_at")


@admin.register(VotingPolicy)
class VotingPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "contest",
        "vote_limit_type",
        "max_votes_per_voter",
        "verification_method",
        "price_per_vote",
        "revenue_share_percentage",
        "allow_anonymous",
    )
    list_filter = ("vote_limit_type", "verification_method", "allow_anonymous")
    search_fields = ("contest__title", "contest__slug")
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        ("Contest", {"fields": ("contest",)}),
        ("Vote Limits", {"fields": ("vote_limit_type", "max_votes_per_voter")}),
        (
            "Verification",
            {"fields": ("verification_method", "required_verification_methods")},
        ),
        ("Pricing", {"fields": ("price_per_vote", "revenue_share_percentage")}),
        ("Privacy", {"fields": ("allow_anonymous",)}),
        (
            "Metadata",
            {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(VoterIdentity)
class VoterIdentityAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "contest",
        "verification_status",
        "verified_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("verification_status", "contest")
    search_fields = ("user__email", "contest__title", "contest__slug")
    readonly_fields = ("id", "created_at", "updated_at")

    fieldsets = (
        (
            "Identity",
            {"fields": ("user", "contest")},
        ),
        (
            "Verification Status",
            {"fields": ("verification_status", "verified_at", "expires_at")},
        ),
        (
            "Metadata",
            {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(VoterVerification)
class VoterVerificationAdmin(admin.ModelAdmin):
    list_display = (
        "voter_identity",
        "method",
        "provider",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "method", "provider")
    search_fields = ("voter_identity__user__email", "voter_identity__contest__title")
    readonly_fields = ("id", "created_at")

    fieldsets = (
        (
            "Verification Attempt",
            {"fields": ("voter_identity", "provider", "method", "status")},
        ),
        (
            "Response Data",
            {"fields": ("verification_response",)},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "completed_at")},
        ),
        (
            "Metadata",
            {"fields": ("id",), "classes": ("collapse",)},
        ),
    )


@admin.register(VoteAttempt)
class VoteAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "contest",
        "contestant",
        "state",
        "vote_quantity",
        "created_at",
        "completed_at",
    )
    list_filter = ("state", "contest", "created_at")
    search_fields = (
        "user__email",
        "contest__title",
        "contestant__name",
        "ip_hash",
        "device_identifier",
    )
    readonly_fields = ("id", "created_at", "completed_at")

    fieldsets = (
        (
            "Vote Attempt Details",
            {
                "fields": (
                    "user",
                    "contest",
                    "contestant",
                    "state",
                    "vote_quantity",
                )
            },
        ),
        (
            "Security & Tracking",
            {
                "fields": (
                    "device_identifier",
                    "ip_hash",
                    "verification_context",
                )
            },
        ),
        (
            "Rejection Details",
            {"fields": ("rejection_reason",)},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "completed_at")},
        ),
        (
            "Metadata",
            {"fields": ("id",), "classes": ("collapse",)},
        ),
    )
