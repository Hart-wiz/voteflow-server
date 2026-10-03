import json
import logging
from decimal import Decimal
from typing import List, Optional

from django.db import transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from ninja import File, Router
from ninja.files import UploadedFile
from ninja.pagination import paginate
from ninja_jwt.authentication import JWTAuth

from payments.models import Transaction, Wallet
from payments.services import calculate_split, verify_paystack_transaction
from voting.models import Vote, VoteAuditLog
from voting.services import create_vote, is_rate_limited

from .models import Contestant, Poll
from .schemas import (
    ContestantCreateSchema,
    ContestantSchema,
    PollCreateSchema,
    PollSchema,
    PollUpdateSchema,
    VoteSchema,
)

logger = logging.getLogger(__name__)
router = Router(tags=["Polls"])


@router.get("/", response=List[PollSchema])
@paginate
def list_polls(request, category: Optional[str] = None, status: Optional[str] = None):
    queryset = (
        Poll.objects.select_related("creator")
        .prefetch_related("contestants")
        .annotate(annotated_votes_count=Sum("contestants__votes"))
        .order_by("-created_at")
    )

    if category:
        queryset = queryset.filter(category=category)
    if status:
        queryset = queryset.filter(status=status)
    else:
        queryset = queryset.exclude(status=Poll.Status.DRAFT)

    return queryset


@router.get("/my-polls", response=List[PollSchema], auth=JWTAuth())
@paginate
def my_polls(request):
    return (
        Poll.objects.filter(creator=request.user)
        .select_related("creator")
        .prefetch_related("contestants")
        .annotate(annotated_votes_count=Sum("contestants__votes"))
        .order_by("-created_at")
    )


@router.get("/{slug}", response=PollSchema)
def get_poll(request, slug: str):
    return get_object_or_404(
        Poll.objects.select_related("creator")
        .prefetch_related("contestants")
        .annotate(annotated_votes_count=Sum("contestants__votes")),
        slug=slug,
    )


@router.post("/", response={201: PollSchema}, auth=JWTAuth())
def create_poll(
    request,
    data: PollCreateSchema,
    image: Optional[UploadedFile] = File(None),
    contestants: Optional[str] = None,  # Expecting JSON string for multipart
):
    poll_data = data.dict(exclude_unset=True)
    if image:
        poll_data["image"] = image

    poll = Poll.objects.create(creator=request.user, **poll_data)

    if contestants:
        try:
            contestants_list = json.loads(contestants)
            for c_data in contestants_list:
                if c_data.get("name"):
                    Contestant.objects.create(poll=poll, **c_data)
        except Exception as e:
            logger.error(f"Error parsing contestants: {e}")

    return 201, poll


@router.patch("/{slug}", response=PollSchema, auth=JWTAuth())
def update_poll(
    request,
    slug: str,
    data: PollUpdateSchema,
    image: Optional[UploadedFile] = File(None),
):
    poll = get_object_or_404(Poll, slug=slug, creator=request.user)

    for attr, value in data.dict(exclude_unset=True).items():
        setattr(poll, attr, value)

    if image:
        poll.image = image

    poll.save()
    return poll


@router.delete("/{slug}", auth=JWTAuth())
def delete_poll(request, slug: str):
    poll = get_object_or_404(Poll, slug=slug, creator=request.user)
    poll.delete()
    return {"success": True}


@router.get("/{slug}/results", response=List[ContestantSchema])
def get_results(request, slug: str):
    poll = get_object_or_404(Poll, slug=slug)
    return poll.contestants.order_by("-votes")


@router.post("/{slug}/contestants", response={201: ContestantSchema}, auth=JWTAuth())
def add_contestant(
    request,
    slug: str,
    data: ContestantCreateSchema,
    image: Optional[UploadedFile] = File(None),
):
    poll = get_object_or_404(Poll, slug=slug)

    if poll.creator != request.user and request.user.role != "admin":
        return 403, {"detail": "You do not have permission to perform this action."}

    contestant_data = data.dict()
    if image:
        contestant_data["image"] = image

    contestant = Contestant.objects.create(poll=poll, **contestant_data)
    return 201, contestant


@router.post("/{slug}/vote")
def vote(request, slug: str, payload: VoteSchema):
    poll = get_object_or_404(Poll, slug=slug)

    # 1. Validate poll is voteable
    if poll.status not in (
        Poll.Status.ACTIVE,
        Poll.Status.ENDING_SOON,
        Poll.Status.NEW,
    ):
        return 400, {
            "success": False,
            "message": "This poll is not currently accepting votes.",
        }

    # 2. Validate contestant belongs to this poll
    contestant = get_object_or_404(Contestant, id=payload.contestant_id, poll=poll)

    quantity = payload.quantity
    email = payload.email
    payment_ref = payload.payment_ref
    ip = request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    # 3. Audit: log attempt
    VoteAuditLog.objects.create(
        poll=poll, ip_address=ip, user_agent=user_agent, action="vote_attempt"
    )

    # 4. Rate limit check
    if not poll.is_paid and is_rate_limited(ip, poll):
        VoteAuditLog.objects.create(
            poll=poll, ip_address=ip, user_agent=user_agent, action="vote_blocked"
        )
        return 429, {"success": False, "message": "Too many votes. Please slow down."}

    # 5. If paid: verify payment
    if poll.is_paid:
        if not payment_ref:
            return 400, {
                "success": False,
                "message": "Payment reference is required for paid polls.",
            }

        expected_amount = Decimal(str(quantity)) * poll.price_per_vote
        paystack_data = verify_paystack_transaction(payment_ref)

        if not paystack_data:
            return 402, {"success": False, "message": "Payment verification failed."}

        paid_amount = Decimal(str(paystack_data.get("amount", 0))) / 100
        if paid_amount < expected_amount:
            return 400, {
                "success": False,
                "message": "Payment amount does not match expected amount.",
            }

    # 6. Atomic vote creation
    with transaction.atomic():
        Contestant.objects.filter(id=contestant.id).update(votes=F("votes") + quantity)

        create_vote(
            poll=poll,
            contestant=contestant,
            voter=request.user if request.user.is_authenticated else None,
            voter_email=email,
            quantity=quantity,
            payment_ref=payment_ref if poll.is_paid else "",
            ip=ip,
            user_agent=user_agent,
            is_paid=poll.is_paid,
            amount=Decimal(str(quantity)) * poll.price_per_vote
            if poll.is_paid
            else Decimal("0"),
        )

        if poll.is_paid:
            total_amount = Decimal(str(quantity)) * poll.price_per_vote
            _, creator_earnings = calculate_split(total_amount)

            try:
                wallet = Wallet.objects.select_for_update().get(user=poll.creator)
                wallet.balance += Decimal(str(creator_earnings))
                wallet.lifetime_earnings += Decimal(str(creator_earnings))
                wallet.save()
            except Wallet.DoesNotExist:
                logger.error(f"Wallet not found for creator {poll.creator.id}")

            Transaction.objects.create(
                user=poll.creator,
                description=f"Earnings from poll: {poll.title}",
                amount=Decimal(str(creator_earnings)),
                status="completed",
                type="earning",
            )

    VoteAuditLog.objects.create(
        poll=poll, ip_address=ip, user_agent=user_agent, action="vote_success"
    )

    return {"success": True, "message": "Vote cast successfully"}
