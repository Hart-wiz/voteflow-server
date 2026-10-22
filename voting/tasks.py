"""Scheduled vote-attempt and suspicious-activity tasks."""

from datetime import datetime, timedelta

from celery import shared_task
from django.db.models import Count
from django.utils import timezone

from .models import AuditLog, VoteAttempt
from .services import expire_vote_attempts


@shared_task(name="voting.tasks.check_vote_attempt_expiration")
def check_vote_attempt_expiration():
    return expire_vote_attempts()


def _record_pattern(key, *, user=None, contest_id=None, metadata=None, window=timedelta(minutes=2)):
    since = timezone.now() - window
    if AuditLog.objects.filter(
        action_type=AuditLog.ActionType.SUSPICIOUS_PATTERN,
        resource_type="SuspiciousPattern",
        resource_id=key,
        timestamp__gte=since,
    ).exists():
        return False
    AuditLog.objects.create(
        user=user,
        action_type=AuditLog.ActionType.SUSPICIOUS_PATTERN,
        resource_type="SuspiciousPattern",
        resource_id=key[:255],
        metadata={"contest_id": str(contest_id) if contest_id else None, **(metadata or {})},
    )
    return True


@shared_task(name="voting.tasks.detect_suspicious_patterns")
def detect_suspicious_patterns(now_iso=None):
    """Log rejection, IP burst, and repeated contestant-attempt patterns."""
    now = datetime.fromisoformat(now_iso) if now_iso else timezone.now()
    created = 0

    cutoff = now - timedelta(minutes=60)
    rejected = (
        VoteAttempt.objects.filter(state=VoteAttempt.State.REJECTED, created_at__gte=cutoff)
        .values("user_id")
        .annotate(total=Count("id"))
        .filter(total__gt=10)
    )
    for row in rejected:
        user = VoteAttempt.objects.filter(user_id=row["user_id"]).select_related("user").first().user
        if _record_pattern(
            f"rejections:user:{row['user_id']}",
            user=user,
            metadata={"pattern": "more_than_10_rejections_in_60_minutes", "count": row["total"]},
            window=timedelta(minutes=60),
        ):
            created += 1

    ten_seconds = now - timedelta(seconds=10)
    ip_bursts = (
        VoteAttempt.objects.filter(created_at__gte=ten_seconds)
        .exclude(ip_hash="")
        .values("contest_id", "ip_hash")
        .annotate(total=Count("id"))
        .filter(total__gt=5)
    )
    for row in ip_bursts:
        if _record_pattern(
            f"ip:{row['ip_hash']}:contest:{row['contest_id']}",
            contest_id=row["contest_id"],
            metadata={"pattern": "more_than_5_attempts_from_ip_in_10_seconds", "count": row["total"]},
            window=timedelta(seconds=10),
        ):
            created += 1

    five_minutes = now - timedelta(minutes=5)
    contestant_bursts = (
        VoteAttempt.objects.filter(created_at__gte=five_minutes)
        .values("user_id", "contestant_id", "contest_id")
        .annotate(total=Count("id"))
        .filter(total__gt=3)
    )
    for row in contestant_bursts:
        user = VoteAttempt.objects.filter(user_id=row["user_id"]).select_related("user").first().user
        if _record_pattern(
            f"user:{row['user_id']}:contestant:{row['contestant_id']}",
            user=user,
            contest_id=row["contest_id"],
            metadata={"pattern": "more_than_3_attempts_for_contestant_in_5_minutes", "count": row["total"]},
            window=timedelta(minutes=5),
        ):
            created += 1
    return created
