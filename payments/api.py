import json
import logging
from typing import List
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.pagination import paginate
from ninja_jwt.authentication import JWTAuth
from ninja.errors import HttpError

from polls.models import Contestant, Poll
from voting.services import create_vote

from .models import Payment, Transaction, Wallet
from .schemas import (
    TransactionSchema,
    WalletSchema,
    WithdrawSchema,
    PayForVoteSchema,
    PayForVoteResponseSchema,
)
from .services import (
    calculate_split,
    initialize_payment,
    verify_paystack_webhook_signature,
    process_withdrawal_transfer,
    process_vote_payment_webhook,
)

logger = logging.getLogger(__name__)
router = Router(tags=["Payments"])
webhooks_router = Router(tags=["Webhooks"])

@router.get("/", response=WalletSchema, auth=JWTAuth())
def get_wallet(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    
    recent_transactions = Transaction.objects.filter(user=request.user).order_by("-created_at")[:10]
    
    return {
        "availableBalance": wallet.balance,
        "pendingEarnings": wallet.pending_earnings,
        "lifetimeEarnings": wallet.lifetime_earnings,
        "transactions": list(recent_transactions)
    }

@router.get("/transactions/", response=List[TransactionSchema], auth=JWTAuth())
@paginate
def list_transactions(request):
    return Transaction.objects.filter(user=request.user).order_by("-created_at")

@router.post("/withdraw/", auth=JWTAuth())
def withdraw(request, payload: WithdrawSchema):
    amount = payload.amount

    with transaction.atomic():
        try:
            wallet = Wallet.objects.select_for_update().get(user=request.user)
        except Wallet.DoesNotExist:
            return 404, {"success": False, "message": "Wallet not found."}

        if wallet.balance < amount:
            return 400, {"success": False, "message": "Insufficient balance."}

        # Deduct from wallet
        wallet.balance -= amount
        wallet.save()

        # Create pending withdrawal transaction
        txn = Transaction.objects.create(
            user=request.user,
            description=f"Withdrawal to {payload.bank_code} - {payload.account_number}",
            amount=-amount,
            status="pending",
            type="withdrawal",
            metadata={
                "bank_code": payload.bank_code,
                "account_number": payload.account_number,
            },
        )

    # Trigger Paystack Transfers API
    try:
        transfer_result = process_withdrawal_transfer(
            reference=str(txn.id),
            amount=amount,
            bank_code=payload.bank_code,
            account_number=payload.account_number,
            account_name=request.user.name or "VoteFlow User"
        )
        
        txn.metadata["transfer_code"] = transfer_result.get("transfer_code")
        if transfer_result.get("status") in ("success", "failed"):
            txn.status = transfer_result["status"]
        txn.save(update_fields=["metadata", "status"])

        if txn.status == "failed":
            with transaction.atomic():
                wallet = Wallet.objects.select_for_update().get(user=request.user)
                wallet.balance += amount
                wallet.save()

    except ValueError as e:
        with transaction.atomic():
            txn.status = "failed"
            txn.save(update_fields=["status"])
            wallet = Wallet.objects.select_for_update().get(user=request.user)
            wallet.balance += amount
            wallet.save()
        return 400, {"success": False, "message": str(e)}

    return {
        "success": True,
        "reference": str(txn.id),
        "message": "Withdrawal queued",
    }

@router.post("/pay/", response=PayForVoteResponseSchema)
def pay_for_vote(request, payload: PayForVoteSchema):
    try:
        result = initialize_payment(
            user=request.user if request.user.is_authenticated else None,
            email=payload.email,
            amount=payload.amount,
            metadata=payload.metadata,
        )
        return {"authorization_url": result["authorization_url"]}
    except Exception as e:
        logger.error(f"Payment initialization failed: {e}")
        return 502, {"error": "Payment initialization failed."}

@router.post("/webhook/paystack/", response={200: dict, 400: dict, 403: dict})
def paystack_webhook(request):
    """
    Handles Paystack webhook callbacks.
    """
    if not verify_paystack_webhook_signature(request):
        logger.warning("Invalid Paystack webhook signature")
        return 403, {"detail": "Invalid signature"}

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return 400, {"detail": "Invalid JSON"}

    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference")

    if not reference:
        return 200, {"status": "ok"}

    # Handle Transfers
    if event in ("transfer.success", "transfer.failed", "transfer.reversed"):
        try:
            txn = Transaction.objects.get(id=reference, type="withdrawal")
        except (Transaction.DoesNotExist, ValueError):
            return 200, {"status": "ok"}

        if txn.status != "pending":
            return 200, {"status": "ok"}

        with transaction.atomic():
            if event == "transfer.success":
                txn.status = "completed"
                txn.save(update_fields=["status"])
            elif event in ("transfer.failed", "transfer.reversed"):
                txn.status = "failed"
                txn.save(update_fields=["status"])
                
                wallet = Wallet.objects.select_for_update().get(user=txn.user)
                wallet.balance -= txn.amount
                wallet.save(update_fields=["balance"])

        return 200, {"status": "ok"}

    # Handle Payments
    if event != "charge.success":
        return 200, {"status": "ok"}

    payment = Payment.objects.filter(reference=reference).first()
    if not payment:
        return 200, {"status": "ok"}

    if payment.processed:
        return 200, {"status": "ok"}

    if payment.amount is None or Decimal(str(data.get("amount", 0))) / Decimal(100) != payment.amount:
        logger.warning("Ignoring Paystack webhook with amount mismatch for %s", reference)
        return 200, {"status": "ok"}

    metadata = data.get("metadata", {})
    poll_id = metadata.get("poll_id")
    contestant_id = metadata.get("contestant_id")
    try:
        quantity = int(metadata.get("quantity", 1))
    except (TypeError, ValueError):
        return 200, {"status": "ok"}
    if quantity < 1 or quantity > 1000:
        return 200, {"status": "ok"}

    if not poll_id or not contestant_id:
        return 200, {"status": "ok"}

    try:
        poll = Poll.objects.get(id=poll_id)
        contestant = Contestant.objects.get(id=contestant_id, poll=poll)
    except (Poll.DoesNotExist, Contestant.DoesNotExist):
        return 200, {"status": "ok"}

    with transaction.atomic():
        payment.status = Payment.Status.CONFIRMED
        payment.processed = True
        payment.save()

        create_vote(
            poll=poll,
            contestant=contestant,
            voter=payment.user,
            voter_email=payment.email,
            quantity=quantity,
            payment_ref=reference,
            is_paid=True,
            amount=payment.amount,
        )

        Contestant.objects.filter(id=contestant.id).update(votes=F("votes") + quantity)

        _, creator_earnings = calculate_split(payment.amount)

        try:
            wallet = Wallet.objects.select_for_update().get(user=poll.creator)
            wallet.balance += Decimal(str(creator_earnings))
            wallet.lifetime_earnings += Decimal(str(creator_earnings))
            wallet.save()
        except Wallet.DoesNotExist:
            pass

        Transaction.objects.create(
            user=poll.creator,
            description=f"Earnings from poll: {poll.title}",
            amount=Decimal(str(creator_earnings)),
            status="completed",
            type="earning",
        )

    return 200, {"status": "ok"}


@webhooks_router.post("/paystack/", response={202: dict, 400: dict, 403: dict})
def vote_paystack_webhook(request):
    """Confirm Kiro vote-attempt payments from a signed Paystack callback."""
    if not verify_paystack_webhook_signature(request):
        return 403, {"detail": "Invalid signature"}
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {"detail": "Invalid JSON"}
    data = payload.get("data") or {}
    try:
        outcome = process_vote_payment_webhook(payload.get("event", ""), data)
    except Exception:
        logger.exception("Could not process Paystack vote webhook")
        raise HttpError(503, "Payment webhook processing is temporarily unavailable.")
    if outcome == "invalid":
        return 202, {"accepted": True, "processed": False}
    return 202, {"accepted": True, "processed": outcome == "confirmed", "status": outcome}
