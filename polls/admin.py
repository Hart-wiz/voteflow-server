from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Poll
from contestants.models import Contestant


class ContestantInline(admin.TabularInline):
    model = Contestant
    extra = 1


@admin.register(Poll)
class PollAdmin(admin.ModelAdmin):
    list_display = ("title", "creator", "vote_type", "visibility", "is_active", "created_at")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ContestantInline]