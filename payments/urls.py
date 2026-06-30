"""
URL routes for the payments (wallet) app.

Included under /api/v1/wallet/ by config/urls.py.
"""

from django.urls import path

from .views import (
    WalletView,
    TransactionListView,
    WithdrawView,
    pay_for_vote,
    paystack_webhook,
)

app_name = "payments"

urlpatterns = [
    path("", WalletView.as_view(), name="wallet"),
    path("transactions/", TransactionListView.as_view(), name="transactions"),
    path("withdraw/", WithdrawView.as_view(), name="withdraw"),
    path("pay/", pay_for_vote, name="pay"),
    path("webhook/paystack/", paystack_webhook, name="paystack-webhook"),
]