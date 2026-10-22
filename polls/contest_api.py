"""Contest-management API for the spec-backed lifecycle model."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile
from ninja.pagination import paginate
from ninja_jwt.authentication import JWTAuth

from accounts.models import User
from accounts.permissions import require_contest_ownership, require_role
from config.errors import ResourceNotFoundError, StateConflictError
from notifications.email import send_transactional_email
from notifications.models import Notification
from pydantic import Field

from voting.models import AuditLog, Vote, VotingPolicy

from .models import Contest, Contestant, ContestantMedia, Livestream as ContestLivestream, Poll
from .services import (
    add_contestant_media,
    create_livestream,
    get_results_for_contest,
    transition_state,
    update_livestream_status,
)

router = Router(tags=["Contests"])


class ContestantInput(Schema):
    name: str
    author: str = ""
    description: str = ""


class PolicyInput(Schema):
    vote_limit_type: str = VotingPolicy.VoteLimitType.UNLIMITED
    max_votes_per_voter: Optional[int] = None
    verification_method: str = VotingPolicy.VerificationMethod.NONE
    required_verification_methods: Optional[list[str]] = None
    price_per_vote: Decimal = Decimal("0.00")
    revenue_share_percentage: int = 80
    allow_anonymous: bool = False


class ContestCreateSchema(Schema):
    title: str
    description: str = ""
    category: str = ""
    slug: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    timezone: str = "UTC"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    results_visibility: str = Contest.ResultsVisibility.AFTER_CLOSE
    contestants: list[ContestantInput]
    policy: PolicyInput = Field(default_factory=PolicyInput)


class ContestUpdateSchema(Schema):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    timezone: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    results_visibility: Optional[str] = None
    tags: Optional[list[str]] = None


class StateTransitionSchema(Schema):
    state: str


class ContestantSchema(Schema):
    id: uuid.UUID
    name: str
    author: str
    description: str
    image: Optional[str]
    votes: int


class ContestSchema(Schema):
    id: uuid.UUID
    slug: str
    title: str
    description: str
    category: str
    state: str
    timezone: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    results_visibility: str
    version: int
    organizer_id: str
    contestants: list[ContestantSchema]
    price_per_vote: Decimal
    created_at: datetime

    @staticmethod
    def resolve_organizer_id(obj):
        return str(obj.organizer_id)

    @staticmethod
    def resolve_contestants(obj):
        if not obj.source_poll_id:
            return []
        return obj.source_poll.contestants.all()

    @staticmethod
    def resolve_price_per_vote(obj):
        try:
            return obj.voting_policy.price_per_vote
        except VotingPolicy.DoesNotExist:
            return Decimal("0.00")


class MediaResultSchema(Schema):
    id: str
    file_url: str
    media_type: str
    caption: str
    display_order: int
    file_size_bytes: int


class MediaInputSchema(Schema):
    media_type: str
    caption: str = ""


class LivestreamInputSchema(Schema):
    stream_url: str
    stream_key: str
    provider: str
    scheduled_start_time: datetime


class LivestreamUpdateSchema(Schema):
    status: str


def _unique_slug(title, requested_slug=None):
    base = slugify(requested_slug or title)[:280] or f"contest-{uuid.uuid4().hex[:10]}"
    slug, suffix = base, 1
    while Contest.objects.filter(slug=slug).exists() or Poll.objects.filter(slug=slug).exists():
        slug = f"{base[:285]}-{suffix}"
        suffix += 1
    return slug


def _apply_policy(policy, payload):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    policy.full_clean()
    policy.save()
    return policy


@router.get("/", response=list[ContestSchema])
@paginate
def list_contests(
    request,
    state: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    ordering: Optional[str] = None,
):
    queryset = Contest.objects.select_related("organizer", "source_poll", "voting_policy").prefetch_related(
        "source_poll__contestants"
    )
    if state:
        queryset = queryset.filter(state=state)
    else:
        queryset = queryset.exclude(state__in=[Contest.State.DRAFT, Contest.State.SUSPENDED])
    if category:
        queryset = queryset.filter(category__iexact=category)
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(organizer__name__icontains=search)
        )
    if ordering == "ending_soon":
        return queryset.order_by("end_time", "created_at")
    if ordering == "alphabetical":
        return queryset.order_by("title")
    return queryset.order_by("-created_at")


@router.get("/{slug}/", response=ContestSchema)
def get_contest(request, slug: str):
    return get_object_or_404(
        Contest.objects.select_related("organizer", "source_poll", "voting_policy").prefetch_related(
            "source_poll__contestants"
        ),
        slug=slug,
    )


@router.post("/", response={201: ContestSchema}, auth=JWTAuth())
@require_role(User.Role.ORGANIZER, User.Role.ADMIN)
def create_contest(request, payload: ContestCreateSchema):
    if not payload.contestants or any(not item.name.strip() for item in payload.contestants):
        raise ValidationError({"contestants": "Add at least one contestant with a name."})
    if payload.start_time and payload.end_time and payload.end_time <= payload.start_time:
        raise ValidationError({"end_time": "Contest end time must be after its start time."})
    slug = _unique_slug(payload.title, payload.slug)
    policy_payload = payload.policy

    try:
        with transaction.atomic():
            poll = Poll.objects.create(
                creator=request.user,
                title=payload.title,
                slug=slug,
                organizer=request.user.name,
                category=payload.category,
                description=payload.description,
                tags=payload.tags,
                status=Poll.Status.DRAFT,
                ends_at=payload.end_time,
                is_paid=policy_payload.price_per_vote > 0,
                price_per_vote=policy_payload.price_per_vote,
            )
            contest = Contest.objects.create(
                organizer=request.user,
                source_poll=poll,
                title=payload.title,
                slug=slug,
                description=payload.description,
                category=payload.category,
                tags=payload.tags,
                timezone=payload.timezone,
                start_time=payload.start_time,
                end_time=payload.end_time,
                results_visibility=payload.results_visibility,
            )
            policy = VotingPolicy(contest=contest)
            _apply_policy(policy, policy_payload)
            for contestant in payload.contestants:
                Contestant.objects.create(
                    poll=poll,
                    name=contestant.name.strip(),
                    author=contestant.author.strip(),
                    description=contestant.description.strip(),
                )
            AuditLog.objects.create(
                user=request.user,
                action_type=AuditLog.ActionType.CONTEST_CREATED,
                resource_type="Contest",
                resource_id=str(contest.pk),
                metadata={"slug": contest.slug},
            )
            return 201, contest
    except IntegrityError as exc:
        raise ValidationError("Contest could not be created because of a data conflict.") from exc


@router.patch("/{slug}/", response=ContestSchema, auth=JWTAuth())
@require_contest_ownership
def update_contest(request, slug: str, payload: ContestUpdateSchema):
    contest = request.contest
    changes = payload.model_dump(exclude_unset=True)
    if "start_time" in changes and changes["start_time"] and contest.end_time and contest.end_time <= changes["start_time"]:
        raise ValidationError({"start_time": "Start time must be before end time."})
    if "end_time" in changes and changes["end_time"] and contest.start_time and changes["end_time"] <= contest.start_time:
        raise ValidationError({"end_time": "End time must be after start time."})
    if contest.state not in (Contest.State.DRAFT, Contest.State.SCHEDULED):
        raise ValidationError("Only draft or scheduled contests can be edited.")
    with transaction.atomic():
        for field, value in changes.items():
            setattr(contest, field, value)
        contest.full_clean()
        contest.save()
        if contest.source_poll_id:
            for source, target in (("title", "title"), ("description", "description"), ("category", "category"), ("tags", "tags"), ("end_time", "ends_at")):
                setattr(contest.source_poll, target, getattr(contest, source))
            contest.source_poll.save()
    return contest


@router.delete("/{slug}/", response={200: dict}, auth=JWTAuth())
@require_contest_ownership
def delete_contest(request, slug: str):
    contest = request.contest
    source_poll = contest.source_poll
    if source_poll and Vote.objects.filter(poll=source_poll).exists():
        raise StateConflictError("A contest with recorded votes cannot be deleted; archive it instead.")
    with transaction.atomic():
        contest.delete()
        if source_poll:
            source_poll.delete()
    return {"success": True}


@router.post("/{slug}/transition/", response=ContestSchema, auth=JWTAuth())
@require_contest_ownership
def transition_contest(request, slug: str, payload: StateTransitionSchema):
    return transition_state(request.contest, payload.state, request.user)


@router.get("/{slug}/results/", response=list[ContestantSchema])
def contest_results(request, slug: str):
    contest = get_object_or_404(Contest.objects.select_related("source_poll"), slug=slug)
    return get_results_for_contest(contest)


@router.post("/{slug}/contestants/", response={201: ContestantSchema}, auth=JWTAuth())
@require_contest_ownership
def add_contestant(request, slug: str, payload: ContestantInput):
    if not request.contest.source_poll_id:
        raise ResourceNotFoundError("This contest has no linked contestant data.")
    contestant = Contestant.objects.create(
        poll=request.contest.source_poll,
        name=payload.name.strip(),
        author=payload.author.strip(),
        description=payload.description.strip(),
    )
    return 201, contestant


@router.post("/{slug}/contestants/{contestant_id}/media/", response={201: MediaResultSchema}, auth=JWTAuth())
@require_contest_ownership
def upload_contestant_media(
    request,
    slug: str,
    contestant_id: str,
    media_type: str = Form(...),
    caption: str = Form(""),
    file: UploadedFile = File(...),
):
    contestant = get_object_or_404(
        Contestant,
        pk=contestant_id,
        poll_id=request.contest.source_poll_id,
    )
    return 201, add_contestant_media(contestant, file, media_type, caption)


@router.post("/{slug}/livestream/", response={201: dict}, auth=JWTAuth())
@require_contest_ownership
def create_contest_livestream(request, slug: str, payload: LivestreamInputSchema):
    livestream = create_livestream(request.contest, **payload.model_dump())
    return 201, {
        "id": str(livestream.pk),
        "stream_url": livestream.stream_url,
        "provider": livestream.provider,
        "status": livestream.status,
        "scheduled_start_time": livestream.scheduled_start_time,
    }


@router.patch("/{slug}/livestream/{livestream_id}/", response={200: dict}, auth=JWTAuth())
@require_contest_ownership
def update_contest_livestream(request, slug: str, livestream_id: str, payload: LivestreamUpdateSchema):
    livestream = get_object_or_404(ContestLivestream, pk=livestream_id, contest=request.contest)
    updated = update_livestream_status(livestream, payload.status)
    return {"id": str(updated.pk), "status": updated.status, "actual_start_time": updated.actual_start_time, "ended_at": updated.ended_at}
