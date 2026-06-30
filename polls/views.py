"""
Views for the polls app.

PollViewSet provides:
    GET    /polls/              → list  (public polls, filterable)
    GET    /polls/my-polls/     → my_polls  (creator's own polls)
    GET    /polls/<slug>/       → retrieve  (single poll with contestants)
    POST   /polls/              → create  (auth required, multipart)
    PATCH  /polls/<slug>/       → partial_update  (owner only, multipart)
    DELETE /polls/<slug>/       → destroy  (owner only)
    POST   /polls/<slug>/vote/  → vote  (cast votes, free or paid)
    GET    /polls/<slug>/results/ → results  (contestants sorted by votes)
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsPollOwner
from voting.models import Vote, VoteAuditLog
from voting.services import create_vote, is_rate_limited
from payments.services import verify_paystack_transaction, calculate_split
from payments.models import Wallet, Transaction

from .models import Contestant, Poll
from .serializers import (
    ContestantSerializer,
    ContestantCreateSerializer,
    PollCreateUpdateSerializer,
    PollDetailSerializer,
    PollListSerializer,
    VoteSerializer,
)

logger = logging.getLogger(__name__)


class PollViewSet(viewsets.ModelViewSet):
    """
    CRUD ViewSet for polls with custom vote and results actions.

    URL routing:
        - List/Create use the collection URL.
        - Retrieve/Update/Delete use slug as the lookup field.
        - vote & results are detail actions on the slug.
    """

    lookup_field = "slug"
    # Filtering & search
    filterset_fields = ["category", "status"]
    search_fields = ["title", "description", "organizer"]
    ordering_fields = ["created_at", "title"]

    def get_queryset(self):
        """
        Base queryset with select_related and prefetch for performance.
        Annotates total votes across all contestants for list views.
        """
        return (
            Poll.objects
            .select_related("creator")
            .prefetch_related("contestants")
            .annotate(
                annotated_votes_count=Sum("contestants__votes")
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action in ("create", "partial_update", "update"):
            return PollCreateUpdateSerializer
        if self.action == "retrieve":
            return PollDetailSerializer
        if self.action == "vote":
            return VoteSerializer
        return PollListSerializer

    def get_permissions(self):
        """
        Permission matrix:
        - list, retrieve, results, vote: anyone
        - create, my_polls: authenticated
        - partial_update, destroy: authenticated poll owner
        """
        if self.action in ("list", "retrieve", "results", "vote"):
            return [AllowAny()]
        if self.action in ("create", "my_polls"):
            return [IsAuthenticated()]
        # update, partial_update, destroy
        return [IsAuthenticated(), IsPollOwner()]

    # ------------------------------------------------------------------
    # Standard CRUD
    # ------------------------------------------------------------------

    def list(self, request, *args, **kwargs):
        """
        GET /polls/
        Returns paginated list of non-draft, non-closed polls by default.
        Supports ?search=, ?category=, ?status=, ?ordering= query params.
        """
        queryset = self.filter_queryset(self.get_queryset())

        # By default exclude drafts (creators see their drafts via my-polls)
        if "status" not in request.query_params:
            queryset = queryset.exclude(status=Poll.Status.DRAFT)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """Set creator to the authenticated user on poll creation."""
        serializer.save(creator=self.request.user)

    def perform_update(self, serializer):
        """Ensure only the owner can update (enforced by permissions)."""
        serializer.save()

    # ------------------------------------------------------------------
    # Custom Actions
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="my-polls")
    def my_polls(self, request):
        """
        GET /polls/my-polls/
        Returns all polls owned by the authenticated user (including drafts).
        """
        queryset = self.filter_queryset(
            self.get_queryset().filter(creator=request.user)
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = PollListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = PollListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="results")
    def results(self, request, slug=None):
        """
        GET /polls/<slug>/results/
        Returns all contestants sorted by votes (descending).
        """
        poll = self.get_object()
        contestants = poll.contestants.order_by("-votes")
        serializer = ContestantSerializer(contestants, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="contestants")
    def add_contestant(self, request, slug=None):
        """
        POST /polls/<slug>/contestants/
        Add a contestant to an existing poll.
        """
        poll = self.get_object()
        
        # Only the poll owner (or an admin) can add contestants
        if poll.creator != request.user and request.user.role != "admin":
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ContestantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Note: image uploads via multipart/form-data are supported here
        serializer.save(poll=poll)
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="vote")
    def vote(self, request, slug=None):
        """
        POST /polls/<slug>/vote/

        Payload:
            {
                "contestant_id": "uuid",
                "quantity": 1,
                "email": "voter@example.com",
                "payment_ref": "..."  // only for paid polls
            }

        Behavior (CRITICAL):
            1. Validate poll is voteable (active or ending_soon).
            2. If paid poll: verify payment_ref with Paystack server-to-server.
            3. Atomically increment contestant.votes by quantity.
            4. Create Vote audit record(s).
            5. If paid: create earning Transaction for poll organizer.
        """
        poll = self.get_object()
        serializer = VoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1. Validate poll is voteable
        if poll.status not in (Poll.Status.ACTIVE, Poll.Status.ENDING_SOON, Poll.Status.NEW):
            return Response(
                {"success": False, "message": "This poll is not currently accepting votes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Validate contestant belongs to this poll
        try:
            contestant = Contestant.objects.get(
                id=data["contestant_id"], poll=poll
            )
        except Contestant.DoesNotExist:
            return Response(
                {"success": False, "message": "Contestant not found in this poll."},
                status=status.HTTP_404_NOT_FOUND,
            )

        quantity = data.get("quantity", 1)
        email = data.get("email", "")
        payment_ref = data.get("payment_ref", "")
        ip = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        # 3. Audit: log attempt
        VoteAuditLog.objects.create(
            poll=poll, ip_address=ip, user_agent=user_agent, action="vote_attempt"
        )

        # 4. Rate limit check (anti-spam for free votes)
        if not poll.is_paid and is_rate_limited(ip, poll):
            VoteAuditLog.objects.create(
                poll=poll, ip_address=ip, user_agent=user_agent, action="vote_blocked"
            )
            return Response(
                {"success": False, "message": "Too many votes. Please slow down."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 5. If paid: verify payment with Paystack
        if poll.is_paid:
            if not payment_ref:
                return Response(
                    {"success": False, "message": "Payment reference is required for paid polls."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            expected_amount = Decimal(str(quantity)) * poll.price_per_vote
            paystack_data = verify_paystack_transaction(payment_ref)

            if not paystack_data:
                return Response(
                    {"success": False, "message": "Payment verification failed."},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )

            # Paystack amount is in kobo (smallest unit); convert to naira
            paid_amount = Decimal(str(paystack_data.get("amount", 0))) / 100
            if paid_amount < expected_amount:
                return Response(
                    {"success": False, "message": "Payment amount does not match expected amount."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 6. Atomic vote creation
        with transaction.atomic():
            # Increment denormalized vote counter
            Contestant.objects.filter(id=contestant.id).update(
                votes=F("votes") + quantity
            )

            # Create Vote record
            vote_record = create_vote(
                poll=poll,
                contestant=contestant,
                voter=request.user if request.user.is_authenticated else None,
                voter_email=email,
                quantity=quantity,
                payment_ref=payment_ref if poll.is_paid else "",
                ip=ip,
                user_agent=user_agent,
                is_paid=poll.is_paid,
                amount=Decimal(str(quantity)) * poll.price_per_vote if poll.is_paid else Decimal("0"),
            )

            # If paid: create earning transaction for poll organizer
            if poll.is_paid:
                total_amount = Decimal(str(quantity)) * poll.price_per_vote
                platform_cut, creator_earnings = calculate_split(total_amount)

                try:
                    wallet = Wallet.objects.select_for_update().get(user=poll.creator)
                    wallet.balance += Decimal(str(creator_earnings))
                    wallet.lifetime_earnings += Decimal(str(creator_earnings))
                    wallet.save()
                except Wallet.DoesNotExist:
                    logger.error(f"Wallet not found for creator {poll.creator.id}")

                # Create transaction record
                Transaction.objects.create(
                    user=poll.creator,
                    description=f"Earnings from poll: {poll.title}",
                    amount=Decimal(str(creator_earnings)),
                    status="completed",
                    type="earning",
                )

        # 7. Audit: log success
        VoteAuditLog.objects.create(
            poll=poll, ip_address=ip, user_agent=user_agent, action="vote_success"
        )

        return Response(
            {"success": True, "message": "Vote cast successfully"},
            status=status.HTTP_200_OK,
        )