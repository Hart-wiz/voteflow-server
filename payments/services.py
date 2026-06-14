import requests
import uuid
from django.conf import settings
from .models import Payment


PAYSTACK_SECRET_KEY = "your_secret_key_here"
PAYSTACK_INIT_URL = "https://api.paystack.co/transaction/initialize"


def initialize_payment(user, email, amount, metadata=None):
    reference = str(uuid.uuid4())

    payment = Payment.objects.create(
        user=user,
        email=email,
        amount=amount,
        reference=reference,
        metadata=metadata or {}
    )

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "email": email,
        "amount": int(amount * 100),  # kobo
        "reference": reference,
        "metadata": metadata or {}
    }

    response = requests.post(PAYSTACK_INIT_URL, json=data, headers=headers)
    res_data = response.json()

    return {
        "payment": payment,
        "authorization_url": res_data["data"]["authorization_url"]
    }



# ......Earnings Split Logic........

PLATFORM_FEE_PERCENT = 20


def calculate_split(amount):
    platform_cut = (PLATFORM_FEE_PERCENT / 100) * float(amount)
    creator_earnings = float(amount) - platform_cut

    return platform_cut, creator_earnings
