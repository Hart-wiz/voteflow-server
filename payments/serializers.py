"""
Serializers for the payments (wallet) app.

Frontend wallet response shape:
    {
        "availableBalance": 5000.00,
        "pendingEarnings": 250.00,
        "lifetimeEarnings": 12000.00,
        "transactions": [...]
    }

Frontend transaction shape:
    { id, date, description, amount, status, type }
"""

from rest_framework import serializers
from .models import Wallet, Transaction


class TransactionSerializer(serializers.ModelSerializer):
    """
    Single transaction record.
    Maps created_at → date for frontend compatibility.
    """
    date = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Transaction
        fields = ["id", "date", "description", "amount", "status", "type"]
        read_only_fields = ["id", "date"]


class WalletSerializer(serializers.ModelSerializer):
    """
    Full wallet overview with recent transactions.
    """
    availableBalance = serializers.DecimalField(
        source="balance", max_digits=12, decimal_places=2
    )
    pendingEarnings = serializers.DecimalField(
        source="pending_earnings", max_digits=12, decimal_places=2
    )
    lifetimeEarnings = serializers.DecimalField(
        source="lifetime_earnings", max_digits=12, decimal_places=2
    )
    transactions = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ["availableBalance", "pendingEarnings", "lifetimeEarnings", "transactions"]

    def get_transactions(self, obj):
        """Return the 10 most recent transactions for the wallet overview."""
        recent = Transaction.objects.filter(user=obj.user).order_by("-created_at")[:10]
        return TransactionSerializer(recent, many=True).data


class WithdrawSerializer(serializers.Serializer):
    """
    POST /wallet/withdraw/
    Payload: { amount, bank_code, account_number }
    """
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    bank_code = serializers.CharField(max_length=10)
    account_number = serializers.CharField(max_length=20)
