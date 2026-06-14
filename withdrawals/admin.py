from django.contrib import admin
from .models import Withdrawal

# Register your models here.

@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "status", "created_at")
    list_filter = ("status",)