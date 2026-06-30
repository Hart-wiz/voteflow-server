"""
Admin configuration for the voting app.
"""

from django.contrib import admin
from .models import Vote, VoteAuditLog


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("contestant", "poll", "quantity", "is_paid", "voter_email", "created_at")
    list_filter = ("is_paid", "poll")
    search_fields = ("voter_email", "payment_ref")
    readonly_fields = ("id", "created_at")


@admin.register(VoteAuditLog)
class VoteAuditLogAdmin(admin.ModelAdmin):
    list_display = ("poll", "action", "ip_address", "created_at")
    list_filter = ("action",)
    readonly_fields = ("id", "created_at")
