from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Withdrawal
from payments.models import Wallet


@api_view(["POST"])
def request_withdrawal(request):
    amount = float(request.data.get("amount"))

    wallet = Wallet.objects.get(user=request.user)

    if wallet.balance < amount:
        return Response({"error": "Insufficient balance"}, status=400)

    withdrawal = Withdrawal.objects.create(
        user=request.user,
        amount=amount
    )

    return Response({"message": "Withdrawal request submitted"})