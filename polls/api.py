import json
import html
import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, Router
from ninja.files import UploadedFile
from ninja.pagination import paginate
from ninja_jwt.authentication import JWTAuth

from accounts.models import User
from accounts.permissions import require_poll_ownership, require_role
from notifications.email import send_transactional_email
from notifications.models import Notification
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


def _poll_queryset():
    return (
        Poll.objects.select_related("creator")
        .prefetch_related("contestants")
        .annotate(annotated_votes_count=Sum("contestants__votes"))
    )


@router.get("/", response=list[PollSchema])
@paginate
def list_polls(
    request,
    category: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    ordering: Optional[str] = None,
):
    queryset = _poll_queryset()
    if category:
        queryset = queryset.filter(category__iexact=category)
    if status:
        queryset = queryset.filter(status=status)
    else:
        queryset = queryset.exclude(status=Poll.Status.DRAFT)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(organizer__icontains=search)
        )
    if ordering == "votes":
        return queryset.order_by("-annotated_votes_count", "-created_at")
    if ordering == "ending_soon":
        return queryset.order_by("ends_at", "-created_at")
    if ordering == "alphabetical":
        return queryset.order_by("title")
    return queryset.order_by("-created_at")


@router.get("/my-polls/", response=list[PollSchema], auth=JWTAuth())
@paginate
def my_polls(request):
    return _poll_queryset().filter(creator=request.user).order_by("-created_at")


@router.get("/{slug}/", response=PollSchema)
def get_poll(request, slug: str):
    return get_object_or_404(_poll_queryset(), slug=slug)


@router.post("/", response={201: PollSchema}, auth=JWTAuth())
@require_role(User.Role.ORGANIZER, User.Role.ADMIN)
def create_poll(
    request,
    data: Form[PollCreateSchema],
    image: Optional[UploadedFile] = File(None),
    contestants: str = Form(""),
):
    poll_data = data.model_dump(exclude_unset=True)
    poll_data["organizer"] = request.user.name
    if poll_data.get("is_paid") and poll_data.get("price_per_vote", Decimal(0)) <= 0:
        return 400, {"detail": "Paid polls must have a price greater than zero."}

    try:
        contestants_data = json.loads(contestants or "[]")
    except json.JSONDecodeError as exc:
        return 400, {"detail": "Contestants must be valid JSON."}
    if not isinstance(contestants_data, list):
        return 400, {"detail": "Contestants must be a list."}
    if not contestants_data or any(not str(item.get("name", "")).strip() for item in contestants_data):
        return 400, {"detail": "Add at least one contestant and provide each contestant's name."}

    with transaction.atomic():
        poll = Poll.objects.create(creator=request.user, image=image, **poll_data)
        for index, item in enumerate(contestants_data):
            contestant_image = request.FILES.get(f"contestant_{index}_image")
            contestant_data = {
                "name": str(item["name"]).strip(),
                "author": str(item.get("author", "")).strip(),
                "description": str(item.get("description", "")).strip(),
            }
            if contestant_image:
                contestant_data["image"] = contestant_image
            Contestant.objects.create(poll=poll, **contestant_data)

    return 201, _poll_queryset().get(pk=poll.pk)


@router.patch("/{slug}/", response=PollSchema, auth=JWTAuth())
@require_poll_ownership
def update_poll(
    request,
    slug: str,
    data: Form[PollUpdateSchema],
    image: Optional[UploadedFile] = File(None),
):
    poll = request.poll

    for attr, value in data.model_dump(exclude_unset=True).items():
        setattr(poll, attr, value)
    if image:
        poll.image = image
    poll.save()
    return _poll_queryset().get(pk=poll.pk)


@router.delete("/{slug}/", auth=JWTAuth())
@require_poll_ownership
def delete_poll(request, slug: str):
    poll = request.poll
    poll.delete()
    return {"success": True}


@router.get("/{slug}/results/", response=list[ContestantSchema])
def get_results(request, slug: str):
    poll = get_object_or_404(Poll, slug=slug)
    return poll.contestants.order_by("-votes", "name")


@router.post("/{slug}/contestants/", response={201: ContestantSchema}, auth=JWTAuth())
@require_poll_ownership
def add_contestant(
    request,
    slug: str,
    data: Form[ContestantCreateSchema],
    image: Optional[UploadedFile] = File(None),
):
    poll = request.poll
    contestant = Contestant.objects.create(poll=poll, image=image, **data.model_dump())
    return 201, contestant


@router.post("/{slug}/vote/", response={200: dict, 400: dict, 402: dict, 429: dict})
def vote(request, slug: str, payload: VoteSchema):
    poll = get_object_or_404(Poll, slug=slug)
    if poll.status not in (Poll.Status.ACTIVE, Poll.Status.ENDING_SOON, Poll.Status.NEW):
        return 400, {"success": False, "message": "This poll is not currently accepting votes."}
    if poll.ends_at and poll.ends_at <= timezone.now():
        return 400, {"success": False, "message": "This poll has ended."}

    contestant = get_object_or_404(Contestant, id=payload.contestant_id, poll=poll)
    quantity = payload.quantity
    email = payload.email or (request.user.email if request.user.is_authenticated else "")
    payment_ref = (payload.payment_ref or "").strip()
    ip = request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    VoteAuditLog.objects.create(poll=poll, ip_address=ip, user_agent=user_agent, action="vote_attempt")
    if not poll.is_paid and is_rate_limited(ip, poll):
        VoteAuditLog.objects.create(poll=poll, ip_address=ip, user_agent=user_agent, action="vote_blocked")
        return 429, {"success": False, "message": "Too many votes. Please slow down."}

    total_amount = Decimal(quantity) * poll.price_per_vote if poll.is_paid else Decimal("0")
    if poll.is_paid:
        if not payment_ref:
            return 400, {"success": False, "message": "Payment reference is required for paid polls."}
        if Vote.objects.filter(payment_ref=payment_ref).exists():
            return 400, {"success": False, "message": "This payment has already been used."}
        paystack_data = verify_paystack_transaction(payment_ref)
        if not paystack_data:
            return 402, {"success": False, "message": "Payment verification failed."}
        paid_amount = Decimal(str(paystack_data.get("amount", 0))) / Decimal(100)
        if paid_amount != total_amount:
            return 400, {"success": False, "message": "Payment amount does not match the vote total."}
        if paystack_data.get("currency") != "NGN":
            return 400, {"success": False, "message": "Payment currency does not match this poll."}
        if email and paystack_data.get("customer", {}).get("email", "").lower() != email.lower():
            return 400, {"success": False, "message": "Payment email does not match the voter email."}

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
            amount=total_amount,
        )

        if poll.is_paid:
            _, creator_earnings = calculate_split(total_amount)
            wallet, _created = Wallet.objects.select_for_update().get_or_create(user=poll.creator)
            wallet.balance += Decimal(str(creator_earnings))
            wallet.lifetime_earnings += Decimal(str(creator_earnings))
            wallet.save(update_fields=["balance", "lifetime_earnings"])
            Transaction.objects.create(
                user=poll.creator,
                description=f"Earnings from poll: {poll.title}",
                amount=Decimal(str(creator_earnings)),
                status=Transaction.Status.COMPLETED,
                type=Transaction.Type.EARNING,
                metadata={"poll_id": str(poll.id), "payment_ref": payment_ref},
            )

        notification = Notification.objects.create(
            receiver=poll.creator,
            title=f"New vote on {poll.title}"[:30],
            description=f"{quantity} vote(s) cast for {contestant.name}.",
            email=poll.creator.email,
        )

    try:
        send_transactional_email(
            to=poll.creator.email,
            subject=f"New vote on {poll.title}",
            text=f"{quantity} vote(s) were cast for {contestant.name} in {poll.title}.",
            html=f"<p>{quantity} vote(s) were cast for <strong>{html.escape(contestant.name)}</strong> in {html.escape(poll.title)}.</p>",
        )
    except Exception:
        # Email delivery must not roll back an already committed vote.
        logger.exception("Could not email vote notification %s", notification.id)

    VoteAuditLog.objects.create(poll=poll, ip_address=ip, user_agent=user_agent, action="vote_success")
    return {"success": True, "message": "Vote cast successfully"}
