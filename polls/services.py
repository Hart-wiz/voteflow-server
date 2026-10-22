"""Contest lifecycle, result-visibility, media, and livestream services."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from config.errors import ExternalServiceError, ResourceNotFoundError, StateConflictError
from voting.models import AuditLog

from .models import Contest, ContestantMedia, Livestream


VALID_STATE_TRANSITIONS = {
    Contest.State.DRAFT: {Contest.State.SCHEDULED, Contest.State.LIVE, Contest.State.CANCELLED},
    Contest.State.SCHEDULED: {Contest.State.LIVE, Contest.State.CANCELLED},
    Contest.State.LIVE: {Contest.State.PAUSED, Contest.State.CLOSED, Contest.State.SUSPENDED},
    Contest.State.PAUSED: {Contest.State.LIVE, Contest.State.CLOSED, Contest.State.CANCELLED, Contest.State.SUSPENDED},
    Contest.State.CLOSED: {Contest.State.ARCHIVED},
    Contest.State.CANCELLED: {Contest.State.ARCHIVED},
    Contest.State.SUSPENDED: {Contest.State.LIVE, Contest.State.CLOSED, Contest.State.ARCHIVED},
    Contest.State.ARCHIVED: set(),
}

MEDIA_LIMIT = 10
MEDIA_MAX_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


def contest_accepts_votes(state):
    """Return whether the contest state currently accepts vote attempts."""
    return state == Contest.State.LIVE


def transition_state(contest, target_state, actor):
    """Validate and atomically apply a contest transition with optimistic locking."""
    if target_state not in Contest.State.values:
        raise ValidationError({"state": "Unknown contest state."})
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Authentication is required.")
    if not (actor.is_superuser or actor.role == User.Role.ADMIN or contest.organizer_id == actor.id):
        raise PermissionDenied("Only the contest owner or an administrator can change its state.")

    with transaction.atomic():
        current = Contest.objects.select_for_update().get(pk=contest.pk)
        if current.version != contest.version:
            raise StateConflictError("The contest was changed by another request.")
        if target_state not in VALID_STATE_TRANSITIONS[current.state]:
            raise ValidationError({"state": f"Transition from {current.state} to {target_state} is not allowed."})

        now = timezone.now()
        current.state = target_state
        current.version += 1
        update_fields = ["state", "version", "updated_at"]
        if target_state == Contest.State.LIVE and current.published_at is None:
            current.published_at = now
            update_fields.append("published_at")
        if target_state == Contest.State.CLOSED:
            current.closed_at = now
            update_fields.append("closed_at")
        current.save(update_fields=update_fields)

        AuditLog.objects.create(
            user=actor,
            action_type=AuditLog.ActionType.CONTEST_STATE_CHANGE,
            resource_type="Contest",
            resource_id=str(current.pk),
            metadata={"from": contest.state, "to": target_state, "version": current.version},
        )

    for field in ("state", "version", "published_at", "closed_at", "updated_at"):
        setattr(contest, field, getattr(current, field))
    return contest


@transaction.atomic
def suspend_contest(contest, actor, reason=""):
    """Allow an administrator to suspend any non-terminal contest."""
    if not actor or not actor.is_authenticated or not (
        actor.is_superuser or actor.role == User.Role.ADMIN
    ):
        raise PermissionDenied("Administrator access is required.")
    current = Contest.objects.select_for_update().get(pk=contest.pk)
    if current.version != contest.version:
        raise StateConflictError("The contest was changed by another request.")
    if current.state in (Contest.State.CLOSED, Contest.State.CANCELLED, Contest.State.ARCHIVED):
        raise ValidationError("A terminal contest cannot be suspended.")
    old_state = current.state
    current.state = Contest.State.SUSPENDED
    current.version += 1
    current.save(update_fields=["state", "version", "updated_at"])
    AuditLog.objects.create(
        user=actor,
        action_type=AuditLog.ActionType.CONTEST_STATE_CHANGE,
        resource_type="Contest",
        resource_id=str(current.pk),
        metadata={"from": old_state, "to": current.state, "reason": reason[:500]},
    )
    contest.state = current.state
    contest.version = current.version
    return contest


def local_contest_time(contest, value):
    """Return an aware contest datetime in its configured IANA timezone."""
    if value is None:
        return None
    if timezone.is_naive(value):
        raise ValidationError("Contest datetimes must be timezone-aware.")
    try:
        zone = ZoneInfo(contest.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError({"timezone": "Unknown IANA timezone."}) from exc
    return value.astimezone(zone)


def close_due_contests(now=None):
    """Close contests whose timezone-aware end time has elapsed."""
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ValueError("now must be timezone-aware")
    due = Contest.objects.filter(
        state__in=[Contest.State.LIVE, Contest.State.PAUSED],
        end_time__isnull=False,
        end_time__lte=now,
    ).only("id", "state", "version", "organizer_id")
    closed = 0
    for contest in due.iterator():
        try:
            transition_state(contest, Contest.State.CLOSED, actor=contest.organizer)
            closed += 1
        except (ValidationError, StateConflictError):
            continue
    return closed


def can_view_results(contest, user=None):
    """Enforce the contest's configured result visibility rule."""
    if contest.results_visibility == Contest.ResultsVisibility.NEVER:
        return False
    if contest.results_visibility == Contest.ResultsVisibility.REAL_TIME:
        return True
    return contest.state in (Contest.State.CLOSED, Contest.State.ARCHIVED)


def add_contestant_media(contestant, uploaded_file, media_type, caption=""):
    """Validate and store up to ten image/video assets per contestant."""
    if media_type not in ContestantMedia.MediaType.values:
        raise ValidationError({"media_type": "Choose IMAGE or VIDEO."})
    extension = Path(uploaded_file.name).suffix.lower()
    allowed = IMAGE_EXTENSIONS if media_type == ContestantMedia.MediaType.IMAGE else VIDEO_EXTENSIONS
    if extension not in allowed:
        raise ValidationError({"file": f"Unsupported {media_type.lower()} file extension."})
    if uploaded_file.size > MEDIA_MAX_BYTES:
        raise ValidationError({"file": "Media files must be 10 MB or smaller."})

    with transaction.atomic():
        # The parent row lock serializes simultaneous attempts at the item cap.
        type(contestant).objects.select_for_update().get(pk=contestant.pk)
        media_count = ContestantMedia.objects.filter(contestant=contestant).count()
        if media_count >= MEDIA_LIMIT:
            raise ValidationError({"media": "A contestant can have at most 10 media items."})

        try:
            stored_name = default_storage.save(
                f"contestants/{contestant.pk}/media/{Path(uploaded_file.name).name}", uploaded_file
            )
            url = default_storage.url(stored_name)
        except Exception as exc:
            raise ExternalServiceError("Could not store contestant media.") from exc

        return ContestantMedia.objects.create(
            contestant=contestant,
            media_type=media_type,
            file_url=url,
            caption=caption[:500],
            display_order=media_count,
            file_size_bytes=uploaded_file.size,
        )


@transaction.atomic
def create_livestream(contest, stream_url, provider, scheduled_start_time, stream_key=""):
    """Create the only livestream record allowed for a contest."""
    locked = Contest.objects.select_for_update().get(pk=contest.pk)
    existing = Livestream.objects.filter(contest=locked).first()
    if existing and existing.status != Livestream.Status.ENDED:
        raise ValidationError({"livestream": "This contest already has an active livestream."})
    if timezone.is_naive(scheduled_start_time):
        raise ValidationError({"scheduled_start_time": "A timezone-aware datetime is required."})
    if existing:
        existing.stream_url = stream_url
        existing.stream_key = stream_key
        existing.provider = provider
        existing.status = Livestream.Status.SCHEDULED
        existing.scheduled_start_time = scheduled_start_time
        existing.actual_start_time = None
        existing.ended_at = None
        existing.viewer_count = 0
        existing.save()
        return existing
    return Livestream.objects.create(
        contest=locked,
        stream_url=stream_url,
        stream_key=stream_key,
        provider=provider,
        scheduled_start_time=scheduled_start_time,
    )


@transaction.atomic
def update_livestream_status(livestream, new_status):
    """Transition a livestream and maintain its actual start/end timestamps."""
    current = Livestream.objects.select_for_update().get(pk=livestream.pk)
    if current.status == Livestream.Status.ENDED:
        raise ValidationError({"status": "An ended livestream cannot be changed."})
    allowed = {
        Livestream.Status.SCHEDULED: {Livestream.Status.LIVE, Livestream.Status.ENDED},
        Livestream.Status.LIVE: {Livestream.Status.ENDED},
    }
    if new_status not in allowed.get(current.status, set()):
        raise ValidationError({"status": f"Transition from {current.status} to {new_status} is not allowed."})
    current.status = new_status
    now = timezone.now()
    if new_status == Livestream.Status.LIVE:
        current.actual_start_time = now
    if new_status == Livestream.Status.ENDED:
        current.ended_at = now
    current.save(update_fields=["status", "actual_start_time", "ended_at", "updated_at"])
    return current


def get_results_for_contest(contest):
    if not can_view_results(contest):
        raise PermissionDenied("Results are not visible yet.")
    if not contest.source_poll_id:
        raise ResourceNotFoundError("This contest has no linked contestant data.")
    return contest.source_poll.contestants.order_by("-votes", "name")
