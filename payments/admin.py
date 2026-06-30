"""
Admin configuration for the payments app.
"""

from django.contrib import admin
from .models import Payment, Wallet, Transaction


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "email", "amount", "status", "processed", "created_at")
    list_filter = ("status", "processed")
    search_fields = ("reference", "email")
    readonly_fields = ("id", "created_at")


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "pending_earnings", "lifetime_earnings", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("id", "created_at")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "type", "amount", "status", "description", "created_at")
    list_filter = ("type", "status")
    search_fields = ("user__email", "description")
    readonly_fields = ("id", "created_at")