"""
Admin configuration for the polls app.
Includes ContestantInline for managing contestants within the poll admin.
"""

from django.contrib import admin
from .models import Poll, Contestant


class ContestantInline(admin.TabularInline):
    model = Contestant
    extra = 1
    fields = ("name", "author", "description", "image", "votes")
    readonly_fields = ("votes",)


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "creator", "category", "status", "is_paid", "created_at")
    list_filter = ("status", "is_paid", "category")
    search_fields = ("title", "organizer", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ContestantInline]
    readonly_fields = ("created_at",)


@admin.register(Contestant)
class ContestantAdmin(admin.ModelAdmin):
    list_display = ("name", "poll", "votes", "created_at")
    list_filter = ("poll",)
    search_fields = ("name",)
    readonly_fields = ("votes",)