from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .services import initialize_payment

import json
from django.http import HttpResponse
from .models import Payment
from voting.services import create_vote
from polls.models import Poll
from contestants.models import Contestant
from .services import calculate_split
from payments.models import Wallet

# Create your views here.


# payment API Endpoint - using this to pay for votes
@api_view(["POST"])
def pay_for_vote(request):
    email = request.data.get("email")
    amount = request.data.get("amount")

    result = initialize_payment(
        user=request.user if request.user.is_authenticated else None,
        email=email,
        amount=amount,
        metadata=request.data.get("metadata", {})
    )

    return Response({
        "authorization_url": result["authorization_url"]
    })



# paystack webhook - where payment is confirmed


def paystack_webhook(request):
    payload = json.loads(request.body)

    event = payload.get("event")
    data = payload.get("data")

    if event == "charge.success":
        reference = data.get("reference")

        payment = Payment.objects.filter(reference=reference).first()

        if payment:
            payment.status = "success"
            payment.save()

            # Extract metadata
            metadata = data.get("metadata", {})
            poll_id = metadata.get("poll_id")
            contestant_id = metadata.get("contestant_id")

            poll = Poll.objects.get(id=poll_id)
            contestant = Contestant.objects.get(id=contestant_id)

            # CREATE PAID VOTE
            create_vote(
                poll=poll,
                contestant=contestant,
                voter=payment.user,
                voter_identifier=payment.email,
                is_paid=True,
                amount=payment.amount
            )

            platform_cut, creator_earnings = calculate_split(payment.amount)

            # Get creator (poll owner via metadata OR poll lookup)
            poll_id = metadata.get("poll_id")
            poll = Poll.objects.get(id=poll_id)
            creator = poll.creator

            # Credit wallet
            wallet = Wallet.objects.get(user=creator)
            wallet.balance += creator_earnings
            wallet.save()

    return HttpResponse(status=200)