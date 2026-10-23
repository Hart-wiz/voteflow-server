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
import html
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from config.errors import ExternalServiceError
from voting.models import AuditLog

from .models import Payment, Transaction, Wallet
from .retries import retry_on_failure

logger = logging.getLogger(__name__)

PAYSTACK_BASE_URL = "https://api.paystack.co"
INLINE_POLL_VOTE_FLOW = "inline_poll_vote"


def _get_headers():
    """Return Paystack API headers with the secret key."""
    if not settings.PAYSTACK_SECRET_KEY:
        raise ImproperlyConfigured("PAYSTACK_SECRET_KEY must be configured for payments.")
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
        provider_reference=reference,
        total_amount=amount,
        metadata=metadata or {},
    )

    data = {
        "email": email,
        "amount": int(Decimal(str(amount)) * 100),  # Convert to kobo
        "reference": reference,
        "metadata": metadata or {},
    }

    @retry_on_failure(max_attempts=3, delay=0.5, backoff=2)
    def initialize():
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=data,
            headers=_get_headers(),
            timeout=15,
        )
        response.raise_for_status()
        res_data = response.json()
        return res_data

    try:
        res_data = initialize()
        return {
            "payment": payment,
            "authorization_url": res_data["data"]["authorization_url"],
        }
    except Exception as e:
        logger.error(f"Paystack initialization failed: {e}")
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        raise


def initialize_vote_payment(vote_attempt):
    """Create and initialize a Paystack payment linked to one vote attempt."""
    from voting.models import VoteAttempt, VotingPolicy
    from voting.services import progress_vote_attempt

    attempt = VoteAttempt.objects.select_related("contest", "contest__voting_policy", "user").get(
        pk=vote_attempt.pk
    )
    if attempt.state != VoteAttempt.State.VERIFIED:
        raise ValueError("The vote attempt must be verified before payment.")
    try:
        policy = attempt.contest.voting_policy
    except VotingPolicy.DoesNotExist as exc:
        raise ValueError("The contest has no voting policy.") from exc
    if policy.price_per_vote <= 0:
        raise ValueError("This contest does not require payment.")
    amount = (policy.price_per_vote * attempt.vote_quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    earnings = (amount * Decimal(policy.revenue_share_percentage) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    reference = str(uuid.uuid4())
    metadata = {
        "vote_attempt_id": str(attempt.pk),
        "contest_id": str(attempt.contest_id),
        "contestant_id": str(attempt.contestant_id),
        "quantity": attempt.vote_quantity,
    }
    payment = Payment.objects.create(
        user=attempt.user,
        vote_attempt=attempt,
        provider_reference=reference,
        reference=reference,
        total_amount=amount,
        amount=amount,
        organizer_earnings=earnings,
        currency="NGN",
        email=attempt.user.email,
        metadata=metadata,
    )

    @retry_on_failure(max_attempts=3, delay=0.5, backoff=2)
    def initialize():
        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json={
                "email": attempt.user.email,
                "amount": int(amount * 100),
                "reference": reference,
                "currency": "NGN",
                "metadata": metadata,
            },
            headers=_get_headers(),
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    try:
        response_data = initialize()
        data = response_data["data"]
        payment.metadata = {**metadata, "authorization_url": data["authorization_url"], "access_code": data.get("access_code")}
        payment.save(update_fields=["metadata"])
        progress_vote_attempt(
            attempt,
            VoteAttempt.State.PAYMENT_PENDING,
            context={"payment_id": str(payment.pk), "provider_reference": reference},
        )
        return payment, data["authorization_url"]
    except Exception as exc:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        AuditLog.objects.create(
            user=attempt.user,
            action_type=AuditLog.ActionType.PAYMENT_FAILED,
            resource_type="Payment",
            resource_id=str(payment.pk),
            metadata={"vote_attempt_id": str(attempt.pk), "reason": "initialization_failed"},
        )
        if isinstance(exc, ExternalServiceError):
            raise
        raise ExternalServiceError("Could not initialize the payment.") from exc


def create_inline_poll_payment(*, poll, contestant, quantity, email, user=None):
    """Create the server-owned payment record used by Paystack InlineJS."""
    if not settings.PAYSTACK_SECRET_KEY or not settings.PAYSTACK_PUBLIC_KEY:
        raise ImproperlyConfigured(
            "PAYSTACK_SECRET_KEY and PAYSTACK_PUBLIC_KEY must be configured for paid votes."
        )

    amount = (poll.price_per_vote * quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if amount > Decimal("999999.99"):
        raise ValueError("The checkout amount exceeds the supported payment limit.")
    reference = f"vf-{uuid.uuid4().hex}"
    metadata = {
        "flow": INLINE_POLL_VOTE_FLOW,
        "poll_id": str(poll.pk),
        "contestant_id": str(contestant.pk),
        "quantity": quantity,
    }
    payment = Payment.objects.create(
        user=user,
        provider_reference=reference,
        reference=reference,
        status=Payment.Status.PENDING,
        total_amount=amount,
        amount=amount,
        currency="NGN",
        email=email,
        metadata=metadata,
    )
    return {
        "payment_id": str(payment.pk),
        "reference": reference,
        "amount": str(amount),
        "amount_minor": int(amount * 100),
        "currency": payment.currency,
        "public_key": settings.PAYSTACK_PUBLIC_KEY,
    }


@transaction.atomic
def confirm_inline_poll_payment(transaction_data, request=None):
    """Idempotently validate a successful Paystack charge and record its vote."""
    from notifications.email import send_transactional_email
    from notifications.models import Notification
    from polls.models import Contestant, Poll, VoteAuditLog
    from voting.services import create_vote

    reference = str(transaction_data.get("reference", ""))
    if not reference:
        return "ignored"

    payment = Payment.objects.select_for_update().filter(
        provider_reference=reference,
        metadata__flow=INLINE_POLL_VOTE_FLOW,
    ).first()
    if not payment:
        return "ignored"

    metadata = payment.metadata or {}
    if transaction_data.get("status") != "success":
        return "pending"
    try:
        paid_amount = Decimal(str(transaction_data.get("amount", 0))) / Decimal(100)
    except Exception:
        return "invalid"

    provider_email = str((transaction_data.get("customer") or {}).get("email") or "")
    if (
        paid_amount != payment.total_amount
        or transaction_data.get("currency") != payment.currency
        or provider_email.lower() != payment.email.lower()
    ):
        return "invalid"
    if payment.status == Payment.Status.CONFIRMED and payment.processed:
        return "duplicate"
    if payment.status != Payment.Status.PENDING:
        return "invalid"

    try:
        poll = Poll.objects.select_related("creator").get(pk=metadata["poll_id"])
        contestant = Contestant.objects.get(pk=metadata["contestant_id"], poll=poll)
        quantity = int(metadata["quantity"])
    except (KeyError, TypeError, ValueError, Poll.DoesNotExist, Contestant.DoesNotExist):
        return "invalid"

    if quantity < 1 or quantity > 1000:
        return "invalid"

    ip = request.META.get("REMOTE_ADDR") if request else None
    user_agent = request.META.get("HTTP_USER_AGENT", "") if request else ""
    Contestant.objects.filter(pk=contestant.pk).update(votes=F("votes") + quantity)
    create_vote(
        poll=poll,
        contestant=contestant,
        voter=payment.user,
        voter_email=payment.email,
        quantity=quantity,
        payment_ref=reference,
        payment=payment,
        ip=ip,
        user_agent=user_agent,
        is_paid=True,
        amount=payment.total_amount,
    )

    _, creator_earnings = calculate_split(payment.total_amount)
    creator_earnings = Decimal(str(creator_earnings)).quantize(Decimal("0.01"))
    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=poll.creator)
    wallet.balance += creator_earnings
    wallet.lifetime_earnings += creator_earnings
    wallet.save(update_fields=["balance", "lifetime_earnings"])
    Transaction.objects.create(
        user=poll.creator,
        description=f"Earnings from poll: {poll.title}",
        amount=creator_earnings,
        status=Transaction.Status.COMPLETED,
        type=Transaction.Type.EARNING,
        metadata={"poll_id": str(poll.pk), "payment_ref": reference},
    )

    payment.status = Payment.Status.CONFIRMED
    payment.processed = True
    payment.organizer_earnings = creator_earnings
    payment.confirmed_at = timezone.now()
    payment.metadata = {**metadata, "gateway_status": "success"}
    payment.save(
        update_fields=["status", "processed", "organizer_earnings", "confirmed_at", "metadata"]
    )
    notification = Notification.objects.create(
        receiver=poll.creator,
        title=f"New vote on {poll.title}"[:30],
        description=f"{quantity} vote(s) cast for {contestant.name}.",
        email=poll.creator.email,
    )
    VoteAuditLog.objects.create(
        poll=poll,
        ip_address=ip,
        user_agent=user_agent,
        action="vote_success",
    )

    def send_vote_email():
        try:
            send_transactional_email(
                to=poll.creator.email,
                subject=f"New vote on {poll.title}",
                text=f"{quantity} vote(s) were cast for {contestant.name} in {poll.title}.",
                html=(
                    f"<p>{quantity} vote(s) were cast for "
                    f"<strong>{html.escape(contestant.name)}</strong> in "
                    f"{html.escape(poll.title)}.</p>"
                ),
            )
        except Exception:
            logger.exception("Could not email vote notification %s", notification.id)

    transaction.on_commit(send_vote_email)
    return "confirmed"


@transaction.atomic
def process_vote_payment_webhook(event, data):
    """Idempotently confirm a paid vote attempt and credit organizer earnings."""
    if event != "charge.success":
        return "ignored"
    reference = str(data.get("reference", ""))
    if not reference:
        return "ignored"
    payment = Payment.objects.select_for_update().filter(provider_reference=reference).first()
    if payment and (payment.metadata or {}).get("flow") == INLINE_POLL_VOTE_FLOW:
        return confirm_inline_poll_payment(data)
    if not payment or not payment.vote_attempt_id:
        return "ignored"
    if payment.status == Payment.Status.CONFIRMED:
        return "duplicate"
    try:
        paid_amount = Decimal(str(data.get("amount", 0))) / Decimal(100)
    except Exception:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        return "invalid"
    if paid_amount != payment.total_amount or data.get("currency") != payment.currency:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        AuditLog.objects.create(
            user=payment.user,
            action_type=AuditLog.ActionType.PAYMENT_FAILED,
            resource_type="Payment",
            resource_id=str(payment.pk),
            metadata={"reason": "amount_or_currency_mismatch"},
        )
        return "invalid"

    attempt = payment.vote_attempt
    if attempt.state != "PAYMENT_PENDING":
        return "invalid"
    payment.status = Payment.Status.CONFIRMED
    payment.processed = True
    payment.confirmed_at = timezone.now()
    payment.metadata = {**(payment.metadata or {}), "gateway_status": "success"}
    payment.save(update_fields=["status", "processed", "confirmed_at", "metadata"])

    from voting.services import progress_vote_attempt
    from payments.models import Transaction, Wallet

    progress_vote_attempt(
        attempt,
        "PAYMENT_CONFIRMED",
        context={"payment_id": str(payment.pk), "confirmed_at": payment.confirmed_at.isoformat()},
    )
    organizer = attempt.contest.organizer
    earnings = payment.organizer_earnings or Decimal("0.00")
    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=organizer)
    wallet.balance += earnings
    wallet.lifetime_earnings += earnings
    wallet.save(update_fields=["balance", "lifetime_earnings"])
    Transaction.objects.create(
        user=organizer,
        description=f"Earnings from contest: {attempt.contest.title}",
        amount=earnings,
        status=Transaction.Status.COMPLETED,
        type=Transaction.Type.EARNING,
        metadata={"payment_id": str(payment.pk), "provider_reference": reference},
    )
    AuditLog.objects.create(
        user=payment.user,
        action_type=AuditLog.ActionType.PAYMENT_CONFIRMED,
        resource_type="Payment",
        resource_id=str(payment.pk),
        metadata={"vote_attempt_id": str(attempt.pk), "organizer_earnings": str(earnings)},
    )
    return "confirmed"


def verify_paystack_transaction(reference):
    """
    Verify a Paystack transaction server-to-server.

    Called during voting to confirm that payment_ref is legitimate
    and the transaction was successful.

    Returns:
        dict with transaction data if successful, None otherwise.
    """
    if not settings.PAYSTACK_SECRET_KEY:
        logger.error("Cannot verify Paystack transaction: PAYSTACK_SECRET_KEY is missing")
        return None
    try:
        @retry_on_failure(max_attempts=3, delay=0.5, backoff=2)
        def verify():
            response = requests.get(
                f"{PAYSTACK_BASE_URL}/transaction/verify/{quote(reference, safe='')}",
                headers=_get_headers(),
                timeout=15,
            )
            response.raise_for_status()
            return response.json()

        res_data = verify()

        if res_data.get("data", {}).get("status") == "success":
            return res_data["data"]
        return None
    except (requests.RequestException, ExternalServiceError) as e:
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
    if not signature or not settings.PAYSTACK_SECRET_KEY:
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
    fee_percent = Decimal(str(getattr(settings, "PLATFORM_FEE_PERCENT", 20)))
    amount = Decimal(str(amount))
    platform_cut = (amount * fee_percent / Decimal(100)).quantize(Decimal("0.01"))
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
        @retry_on_failure(max_attempts=3, delay=0.5, backoff=2)
        def create_recipient():
            response = requests.post(
                f"{PAYSTACK_BASE_URL}/transferrecipient",
                json=recipient_data,
                headers=_get_headers(),
                timeout=15,
            )
            response.raise_for_status()
            return response.json()

        recipient_code = create_recipient()["data"]["recipient_code"]
    except (requests.RequestException, ExternalServiceError) as e:
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
        @retry_on_failure(max_attempts=3, delay=0.5, backoff=2)
        def initiate_transfer():
            response = requests.post(
                f"{PAYSTACK_BASE_URL}/transfer",
                json=transfer_data,
                headers=_get_headers(),
                timeout=15,
            )
            response.raise_for_status()
            return response.json()["data"]

        data = initiate_transfer()
        return {
            "status": data["status"], # 'pending' or 'success' or 'failed'
            "transfer_code": data["transfer_code"]
        }
    except (requests.RequestException, ExternalServiceError) as e:
        logger.error(f"Failed to initiate transfer: {e}")
        raise ValueError("Failed to initiate transfer with Paystack")

