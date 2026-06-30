"""
Payment services for VoteFlow.

Handles:
    - Paystack payment initialization
    - Paystack transaction verification (server-to-server)
    - Paystack webhook signature verification (HMAC)
    - Earnings split calculation
"""

import hashlib
import hmac
import logging
import uuid
from decimal import Decimal

import requests
from django.conf import settings

from .models import Payment

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = "https://api.paystack.co"


def _get_headers():
    """Return Paystack API headers with the secret key."""
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def initialize_payment(user, email, amount, metadata=None):
    """
    Initialize a Paystack transaction.

    Creates a Payment record and calls the Paystack API to get
    the authorization URL for the frontend to redirect to.

    Returns:
        dict with 'payment' and 'authorization_url'
    """
    reference = str(uuid.uuid4())

    payment = Payment.objects.create(
        user=user,
        email=email,
        amount=amount,
        reference=reference,
        metadata=metadata or {},
    )

    data = {
        "email": email,
        "amount": int(Decimal(str(amount)) * 100),  # Convert to kobo
        "reference": reference,
        "metadata": metadata or {},
    }

    try:
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=data,
            headers=_get_headers(),
            timeout=15,
        )
        response.raise_for_status()
        res_data = response.json()

        return {
            "payment": payment,
            "authorization_url": res_data["data"]["authorization_url"],
        }
    except requests.RequestException as e:
        logger.error(f"Paystack initialization failed: {e}")
        payment.status = "failed"
        payment.save()
        raise


def verify_paystack_transaction(reference):
    """
    Verify a Paystack transaction server-to-server.

    Called during voting to confirm that payment_ref is legitimate
    and the transaction was successful.

    Returns:
        dict with transaction data if successful, None otherwise.
    """
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_get_headers(),
            timeout=15,
        )
        response.raise_for_status()
        res_data = response.json()

        if res_data.get("data", {}).get("status") == "success":
            return res_data["data"]
        return None
    except requests.RequestException as e:
        logger.error(f"Paystack verification failed for {reference}: {e}")
        return None


def verify_paystack_webhook_signature(request):
    """
    Verify the HMAC-SHA512 signature of a Paystack webhook request.

    Paystack signs webhooks with the secret key. We must verify the
    signature to prevent forged webhook calls.

    Returns:
        True if signature is valid, False otherwise.
    """
    signature = request.headers.get("X-Paystack-Signature", "")
    if not signature:
        return False

    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        request.body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def calculate_split(amount):
    """
    Calculate platform fee and creator earnings.

    Args:
        amount: Total payment amount (Decimal or float)

    Returns:
        tuple of (platform_cut, creator_earnings) as floats
    """
    fee_percent = getattr(settings, "PLATFORM_FEE_PERCENT", 20)
    amount = float(amount)
    platform_cut = (fee_percent / 100) * amount
    creator_earnings = amount - platform_cut
    return platform_cut, creator_earnings


def process_withdrawal_transfer(reference, amount, bank_code, account_number, account_name="User Wallet"):
    """
    Process a withdrawal via Paystack Transfers API.
    
    1. Create a Transfer Recipient.
    2. Initiate the Transfer.
    
    Args:
        reference: The transaction UUID string to use as the transfer reference
        amount: Amount in Naira (Decimal or float)
        bank_code: Bank code for the destination bank
        account_number: Destination account number
        account_name: Name of the account holder
        
    Returns:
        dict containing 'status' and 'transfer_code'
    """
    # 1. Create Transfer Recipient
    recipient_data = {
        "type": "nuban",
        "name": account_name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": "NGN"
    }
    
    try:
        res = requests.post(
            f"{PAYSTACK_BASE_URL}/transferrecipient",
            json=recipient_data,
            headers=_get_headers(),
            timeout=15,
        )
        res.raise_for_status()
        recipient_code = res.json()["data"]["recipient_code"]
    except requests.RequestException as e:
        logger.error(f"Failed to create transfer recipient: {e}")
        raise ValueError("Could not validate bank details with Paystack")

    # 2. Initiate Transfer
    transfer_data = {
        "source": "balance",
        "amount": int(Decimal(str(amount)) * 100),  # Convert to kobo
        "reference": reference,
        "recipient": recipient_code,
        "reason": "VoteFlow Wallet Withdrawal"
    }
    
    try:
        res = requests.post(
            f"{PAYSTACK_BASE_URL}/transfer",
            json=transfer_data,
            headers=_get_headers(),
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()["data"]
        return {
            "status": data["status"], # 'pending' or 'success' or 'failed'
            "transfer_code": data["transfer_code"]
        }
    except requests.RequestException as e:
        logger.error(f"Failed to initiate transfer: {e}")
        raise ValueError("Failed to initiate transfer with Paystack")

