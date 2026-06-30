"""
Views for the payments (wallet) app.

Endpoints (included under /api/v1/wallet/):
    GET   /                   → WalletView      (balance overview + recent txns)
    GET   /transactions/      → TransactionListView  (paginated history)
    POST  /withdraw/          → WithdrawView    (request withdrawal)
    POST  /webhook/paystack/  → paystack_webhook  (Paystack callback)
    POST  /pay/               → pay_for_vote    (initialize Paystack payment)
"""

import json
import logging
from decimal import Decimal

from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from polls.models import Contestant, Poll
from voting.services import create_vote

from .models import Payment, Transaction, Wallet
from .serializers import TransactionSerializer, WalletSerializer, WithdrawSerializer
from .services import (
    calculate_split,
    initialize_payment,
    verify_paystack_webhook_signature,
    process_withdrawal_transfer,
)

logger = logging.getLogger(__name__)


class WalletView(GenericAPIView):
    """
    GET /wallet/
    Returns the authenticated user's wallet overview with recent transactions.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WalletSerializer

    def get(self, request):
        try:
            wallet = Wallet.objects.get(user=request.user)
        except Wallet.DoesNotExist:
            # Auto-create wallet if missing (safety net)
            wallet = Wallet.objects.create(user=request.user)

        serializer = self.get_serializer(wallet)
        return Response(serializer.data)


class TransactionListView(ListAPIView):
    """
    GET /wallet/transactions/?page=1
    Returns paginated transaction history for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user).order_by("-created_at")


class WithdrawView(GenericAPIView):
    """
    POST /wallet/withdraw/
    Payload: { amount, bank_code, account_number }

    Validates balance, creates a pending withdrawal transaction,
    and optionally triggers Paystack Transfers API.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        amount = data["amount"]

        with transaction.atomic():
            try:
                wallet = Wallet.objects.select_for_update().get(user=request.user)
            except Wallet.DoesNotExist:
                return Response(
                    {"success": False, "message": "Wallet not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if wallet.balance < amount:
                return Response(
                    {"success": False, "message": "Insufficient balance."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Deduct from wallet
            wallet.balance -= amount
            wallet.save()

            # Create pending withdrawal transaction
            txn = Transaction.objects.create(
                user=request.user,
                description=f"Withdrawal to {data['bank_code']} - {data['account_number']}",
                amount=-amount,  # Negative for debits
                status="pending",
                type="withdrawal",
                metadata={
                    "bank_code": data["bank_code"],
                    "account_number": data["account_number"],
                },
            )

        # Trigger Paystack Transfers API
        try:
            transfer_result = process_withdrawal_transfer(
                reference=str(txn.id),
                amount=amount,
                bank_code=data["bank_code"],
                account_number=data["account_number"],
                account_name=request.user.name or "VoteFlow User"
            )
            
            # Update transaction with transfer code
            txn.metadata["transfer_code"] = transfer_result.get("transfer_code")
            # Paystack might return 'success' immediately if instant
            if transfer_result.get("status") in ("success", "failed"):
                txn.status = transfer_result["status"]
            txn.save(update_fields=["metadata", "status"])

            if txn.status == "failed":
                # Refund if immediate failure
                with transaction.atomic():
                    wallet = Wallet.objects.select_for_update().get(user=request.user)
                    wallet.balance += amount
                    wallet.save()

        except ValueError as e:
            # Revert the transaction if Paystack API call failed
            with transaction.atomic():
                txn.status = "failed"
                txn.save(update_fields=["status"])
                wallet = Wallet.objects.select_for_update().get(user=request.user)
                wallet.balance += amount
                wallet.save()
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "success": True,
            "reference": str(txn.id),
            "message": "Withdrawal queued",
        })


@api_view(["POST"])
@permission_classes([AllowAny])
def pay_for_vote(request):
    """
    POST /wallet/pay/
    Initialize a Paystack payment for a paid vote.
    """
    email = request.data.get("email")
    amount = request.data.get("amount")

    if not email or not amount:
        return Response(
            {"error": "Email and amount are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = initialize_payment(
            user=request.user if request.user.is_authenticated else None,
            email=email,
            amount=amount,
            metadata=request.data.get("metadata", {}),
        )
        return Response({"authorization_url": result["authorization_url"]})
    except Exception as e:
        logger.error(f"Payment initialization failed: {e}")
        return Response(
            {"error": "Payment initialization failed."},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def paystack_webhook(request):
    """
    POST /wallet/webhook/paystack/

    Handles Paystack webhook callbacks.
    Verifies HMAC signature, processes charge.success events:
        1. Marks payment as successful
        2. Creates paid vote
        3. Splits earnings and credits creator wallet
    """
    # Verify webhook signature
    if not verify_paystack_webhook_signature(request):
        logger.warning("Invalid Paystack webhook signature")
        return Response(status=status.HTTP_403_FORBIDDEN)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return Response(status=status.HTTP_400_BAD_REQUEST)

    event = payload.get("event")
    data = payload.get("data", {})
    reference = data.get("reference")

    if not reference:
        return HttpResponse(status=200)

    # --- Handle Transfers (Withdrawals) ---
    if event in ("transfer.success", "transfer.failed", "transfer.reversed"):
        try:
            txn = Transaction.objects.get(id=reference, type="withdrawal")
        except (Transaction.DoesNotExist, ValueError):
            # ValueError occurs if reference is not a valid UUID (which means it's not a withdrawal)
            return HttpResponse(status=200)

        # Prevent duplicate webhook processing
        if txn.status != "pending":
            return HttpResponse(status=200)

        with transaction.atomic():
            if event == "transfer.success":
                txn.status = "completed"
                txn.save(update_fields=["status"])
            elif event in ("transfer.failed", "transfer.reversed"):
                txn.status = "failed"
                txn.save(update_fields=["status"])
                
                # Refund the wallet
                try:
                    wallet = Wallet.objects.select_for_update().get(user=txn.user)
                    # Note: txn.amount is negative for withdrawals, so we subtract to add it back
                    wallet.balance -= txn.amount
                    wallet.save(update_fields=["balance"])
                except Wallet.DoesNotExist:
                    logger.error(f"Wallet not found for user {txn.user_id} during transfer refund.")

        return HttpResponse(status=200)

    # --- Handle Payments (Votes) ---
    if event != "charge.success":
        return HttpResponse(status=200)

    reference = data.get("reference")
    if not reference:
        return HttpResponse(status=200)

    payment = Payment.objects.filter(reference=reference).first()
    if not payment:
        logger.warning(f"Payment not found for reference: {reference}")
        return HttpResponse(status=200)

    # Prevent duplicate processing
    if payment.processed:
        return HttpResponse(status=200)

    # Extract metadata
    metadata = data.get("metadata", {})
    poll_id = metadata.get("poll_id")
    contestant_id = metadata.get("contestant_id")
    quantity = metadata.get("quantity", 1)

    if not poll_id or not contestant_id:
        logger.error(f"Missing poll_id or contestant_id in webhook metadata: {reference}")
        return HttpResponse(status=200)

    try:
        poll = Poll.objects.get(id=poll_id)
        contestant = Contestant.objects.get(id=contestant_id, poll=poll)
    except (Poll.DoesNotExist, Contestant.DoesNotExist) as e:
        logger.error(f"Poll/Contestant not found in webhook: {e}")
        return HttpResponse(status=200)

    with transaction.atomic():
        # Mark payment as successful
        payment.status = "success"
        payment.processed = True
        payment.save()

        # Create paid vote
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

        # Increment contestant vote count
        from django.db.models import F
        Contestant.objects.filter(id=contestant.id).update(
            votes=F("votes") + quantity
        )

        # Split earnings
        platform_cut, creator_earnings = calculate_split(payment.amount)

        # Credit creator wallet
        try:
            wallet = Wallet.objects.select_for_update().get(user=poll.creator)
            wallet.balance += Decimal(str(creator_earnings))
            wallet.lifetime_earnings += Decimal(str(creator_earnings))
            wallet.save()
        except Wallet.DoesNotExist:
            logger.error(f"Wallet not found for creator: {poll.creator.id}")

        # Record earning transaction
        Transaction.objects.create(
            user=poll.creator,
            description=f"Earnings from poll: {poll.title}",
            amount=Decimal(str(creator_earnings)),
            status="completed",
            type="earning",
        )

    return HttpResponse(status=200)