from django.urls import path
from .views import pay_for_vote, paystack_webhook

urlpatterns = [
    path("pay/", pay_for_vote),
    path("webhook/paystack/", paystack_webhook),
]