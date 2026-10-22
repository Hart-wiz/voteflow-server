"""Voting service functions shared by API and payment workflows."""

import json
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db import connection
from django.db.models import F, Max
from django.utils import timezone

from config.errors import StateConflictError
from polls.models import Contest, Poll
from polls.services import contest_accepts_votes

from .models import AuditLog, Vote, VoteAttempt, VoterIdentity
from .policies import check_vote_limit, is_identity_verified, requires_verification
from .utils import extract_device_fingerprint, hash_ip_address_safe


VOTE_ATTEMPT_TRANSITIONS = {
    VoteAttempt.State.STARTED: {
        VoteAttempt.State.IDENTITY_CHECK,
        VoteAttempt.State.VERIFIED,
        VoteAttempt.State.REJECTED,
        VoteAttempt.State.FAILED,
    },
    VoteAttempt.State.IDENTITY_CHECK: {
        VoteAttempt.State.VERIFIED,
        VoteAttempt.State.REJECTED,
        VoteAttempt.State.FAILED,
    },
    VoteAttempt.State.VERIFIED: {
        VoteAttempt.State.PAYMENT_PENDING,
        VoteAttempt.State.PAYMENT_CONFIRMED,
        VoteAttempt.State.COMPLETED,
        VoteAttempt.State.REJECTED,
        VoteAttempt.State.FAILED,
    },
    VoteAttempt.State.PAYMENT_PENDING: {
        VoteAttempt.State.PAYMENT_CONFIRMED,
        VoteAttempt.State.REJECTED,
        VoteAttempt.State.EXPIRED,
        VoteAttempt.State.FAILED,
    },
    VoteAttempt.State.PAYMENT_CONFIRMED: {
        VoteAttempt.State.COMPLETED,
        VoteAttempt.State.FAILED,
    },
    VoteAttempt.State.COMPLETED: set(),
    VoteAttempt.State.REJECTED: set(),
    VoteAttempt.State.EXPIRED: set(),
    VoteAttempt.State.FAILED: set(),
}


def is_vote_attempt_transition_allowed(current_state, target_state):
    """Return whether a vote attempt may move along the declared state graph."""
    return target_state in VOTE_ATTEMPT_TRANSITIONS.get(current_state, set())


def payment_status_is_confirmed(status):
    """Return whether a payment-provider status is safe for vote commitment."""
    return status == "CONFIRMED"


def create_vote(
    *,
    poll,
    contestant,
    voter=None,
    voter_email="",
    quantity=1,
    payment_ref="",
    ip=None,
    user_agent="",
    is_paid=False,
    amount=0,
    payment=None,
):
    """Create an immutable vote record with a per-poll sequence number."""
    with transaction.atomic():
        # Serialize number allocation on the poll row so simultaneous votes
        # cannot receive the same sequence number.
        Poll.objects.select_for_update().get(pk=poll.pk)
        last_vote_number = Vote.objects.filter(poll=poll).aggregate(
            last_number=Max("vote_number")
        )["last_number"] or 0
        vote = Vote.objects.create(
            poll=poll,
            contestant=contestant,
            voter=voter,
            voter_email=voter_email,
            quantity=quantity,
            vote_quantity=quantity,
            vote_number=last_vote_number + 1,
            payment=payment,
            payment_ref=payment_ref,
            ip_address=ip,
            ip_hash=hash_ip_address(ip) if ip else "",
            device_identifier=user_agent[:255],
            device_fingerprint=user_agent[:255],
            user_agent=user_agent,
            is_paid=is_paid,
            amount=amount,
        )
        AuditLog.objects.create(
            user=voter,
            action_type=AuditLog.ActionType.VOTE_COMPLETED,
            resource_type="Vote",
            resource_id=str(vote.pk),
            ip_hash=hash_ip_address_safe(ip),
            device_fingerprint=user_agent[:512],
            metadata={"poll_id": str(poll.pk), "contestant_id": str(contestant.pk), "quantity": quantity},
        )
        return vote


def is_rate_limited(ip, poll):
    """Allow no more than three recent free vote attempts per IP and poll."""
    if not ip:
        return False
    time_limit = timezone.now() - timedelta(seconds=10)
    recent_votes = Vote.objects.filter(
        ip_address=ip,
        poll=poll,
        created_at__gte=time_limit,
    ).count()
    return recent_votes >= 3


def has_already_voted(user, poll):
    """Return whether an authenticated user has already voted in this poll."""
    if not user or not user.is_authenticated:
        return False
    return Vote.objects.filter(voter=user, poll=poll).exists()


@transaction.atomic
def initiate_vote_attempt(user, contest, contestant, quantity, request=None):
    """Validate a live contest and create an auditable vote attempt."""
    contest = Contest.objects.select_for_update().get(pk=contest.pk)
    if not contest_accepts_votes(contest.state):
        raise ValidationError("Votes are accepted only while a contest is LIVE.")
    if contest.end_time and contest.end_time <= timezone.now():
        raise ValidationError("This contest has ended.")
    if not contest.source_poll_id or contestant.poll_id != contest.source_poll_id:
        raise ValidationError("The contestant does not belong to this contest.")
    check_vote_limit(user, contest, quantity)

    verification_required = requires_verification(contest)
    if not verification_required and user.is_authenticated:
        initial_state = VoteAttempt.State.VERIFIED
    elif verification_required and user.is_authenticated and is_identity_verified(user, contest):
        initial_state = VoteAttempt.State.VERIFIED
    else:
        initial_state = VoteAttempt.State.IDENTITY_CHECK if verification_required else VoteAttempt.State.VERIFIED

    ip_address = request.META.get("REMOTE_ADDR") if request else ""
    fingerprint = extract_device_fingerprint(request) if request else "unknown"
    attempt = VoteAttempt.objects.create(
        user=user,
        contest=contest,
        contestant=contestant,
        vote_quantity=quantity,
        state=initial_state,
        ip_hash=hash_ip_address_safe(ip_address),
        device_identifier=fingerprint[:255],
        verification_context={"started_at": timezone.now().isoformat()},
    )
    AuditLog.objects.create(
        user=user,
        action_type=AuditLog.ActionType.VOTE_STARTED,
        resource_type="VoteAttempt",
        resource_id=str(attempt.pk),
        ip_hash=attempt.ip_hash,
        device_fingerprint=fingerprint[:512],
        metadata={"contest_id": str(contest.pk), "quantity": quantity},
    )
    return attempt


@transaction.atomic
def progress_vote_attempt(vote_attempt, new_state, context=None, rejection_reason=""):
    """Move an attempt through its explicit state graph."""
    attempt = VoteAttempt.objects.select_for_update().get(pk=vote_attempt.pk)
    if not is_vote_attempt_transition_allowed(attempt.state, new_state):
        raise ValidationError(f"Transition from {attempt.state} to {new_state} is not allowed.")
    if new_state == VoteAttempt.State.REJECTED and not rejection_reason:
        raise ValidationError("A rejection reason is required.")
    if context:
        attempt.verification_context = {**(attempt.verification_context or {}), **context}
        if len(json.dumps(attempt.verification_context, default=str).encode("utf-8")) > 100 * 1024:
            raise ValidationError("Verification context exceeds the 100 KB limit.")
    attempt.state = new_state
    update_fields = ["state"]
    if context:
        update_fields.append("verification_context")
    if rejection_reason:
        attempt.rejection_reason = rejection_reason[:500]
        update_fields.append("rejection_reason")
    if new_state in {
        VoteAttempt.State.COMPLETED,
        VoteAttempt.State.REJECTED,
        VoteAttempt.State.EXPIRED,
        VoteAttempt.State.FAILED,
    }:
        attempt.completed_at = timezone.now()
        update_fields.append("completed_at")
    attempt.save(update_fields=update_fields)
    if new_state == VoteAttempt.State.REJECTED:
        AuditLog.objects.create(
            user=attempt.user,
            action_type=AuditLog.ActionType.VOTE_REJECTED,
            resource_type="VoteAttempt",
            resource_id=str(attempt.pk),
            ip_hash=attempt.ip_hash,
            device_fingerprint=attempt.device_identifier[:512],
            metadata={"reason": attempt.rejection_reason, "context": context or {}},
        )
    elif new_state == VoteAttempt.State.FAILED:
        AuditLog.objects.create(
            user=attempt.user,
            action_type=AuditLog.ActionType.VOTE_FAILED,
            resource_type="VoteAttempt",
            resource_id=str(attempt.pk),
            ip_hash=attempt.ip_hash,
            device_fingerprint=attempt.device_identifier[:512],
            metadata={"reason": attempt.rejection_reason, "context": context or {}},
        )
    return attempt


@transaction.atomic
def commit_vote(vote_attempt, payment=None):
    """Commit a verified vote, one immutable row per vote, and update counters."""
    if connection.vendor == "postgresql":
        # Must precede application queries in this transaction.
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    attempt = VoteAttempt.objects.select_for_update().select_related(
        "contest", "contestant", "user"
    ).get(pk=vote_attempt.pk)
    if attempt.state not in (VoteAttempt.State.VERIFIED, VoteAttempt.State.PAYMENT_CONFIRMED):
        raise ValidationError("The vote attempt is not ready to commit.")
    if not is_identity_verified(attempt.user, attempt.contest):
        raise ValidationError("Voter identity has not been verified.")

    from payments.models import Payment
    from voting.models import VotingPolicy

    policy = getattr(attempt.contest, "voting_policy", None)
    paid = bool(policy and policy.price_per_vote > 0)
    if paid:
        payment = payment or Payment.objects.filter(vote_attempt=attempt).order_by("-created_at").first()
        if not payment or not payment_status_is_confirmed(payment.status):
            raise ValidationError("A confirmed payment is required before committing this vote.")
        expected_amount = policy.price_per_vote * attempt.vote_quantity
        actual_amount = payment.total_amount if payment.total_amount is not None else payment.amount
        if actual_amount != expected_amount or payment.currency != "NGN":
            raise ValidationError("The confirmed payment does not match this vote attempt.")
        if payment.vote_attempt_id != attempt.pk:
            raise ValidationError("The payment belongs to another vote attempt.")
    elif payment is not None:
        raise ValidationError("Free votes cannot be associated with a payment.")

    poll = attempt.contest.source_poll
    if poll is None or attempt.contestant.poll_id != poll.pk:
        raise ValidationError("The contest has no matching contestant data.")
    Poll.objects.select_for_update().get(pk=poll.pk)
    identity, _ = VoterIdentity.objects.get_or_create(user=attempt.user, contest=attempt.contest)
    previous = Vote.objects.filter(poll=poll).aggregate(last=Max("vote_number"))["last"] or 0

    rows = [
        Vote(
            poll=poll,
            contestant=attempt.contestant,
            voter_identity=identity,
            voter=attempt.user,
            vote_number=previous + index,
            vote_quantity=1,
            quantity=1,
            payment=payment,
            payment_ref=(payment.provider_reference or payment.reference or "") if payment else "",
            device_identifier=attempt.device_identifier,
            device_fingerprint=attempt.device_identifier,
            ip_hash=attempt.ip_hash,
            is_paid=paid,
            amount=(policy.price_per_vote if paid else 0),
        )
        for index in range(1, attempt.vote_quantity + 1)
    ]
    Vote.objects.bulk_create(rows)
    type(attempt.contestant).objects.filter(pk=attempt.contestant_id).update(
        votes=F("votes") + attempt.vote_quantity
    )
    attempt.state = VoteAttempt.State.COMPLETED
    attempt.completed_at = timezone.now()
    attempt.save(update_fields=["state", "completed_at"])
    from notifications.models import Notification

    Notification.objects.create(
        receiver=attempt.contest.organizer,
        title=f"New vote on {attempt.contest.title}"[:30],
        description=f"{attempt.vote_quantity} vote(s) cast for {attempt.contestant.name}.",
        email=attempt.contest.organizer.email,
    )
    transaction.on_commit(
        lambda: _send_vote_notification(
            attempt.contest.organizer.email,
            attempt.contest.title,
            attempt.contestant.name,
            attempt.vote_quantity,
        )
    )
    AuditLog.objects.create(
        user=attempt.user,
        action_type=AuditLog.ActionType.VOTE_COMPLETED,
        resource_type="VoteAttempt",
        resource_id=str(attempt.pk),
        ip_hash=attempt.ip_hash,
        device_fingerprint=attempt.device_identifier[:512],
        metadata={"quantity": attempt.vote_quantity, "poll_id": str(poll.pk)},
    )
    return rows


def _send_vote_notification(email, contest_title, contestant_name, quantity):
    from html import escape
    import logging

    from notifications.email import send_transactional_email

    try:
        send_transactional_email(
            to=email,
            subject=f"New vote on {contest_title}",
            text=f"{quantity} vote(s) were cast for {contestant_name} in {contest_title}.",
            html=f"<p>{quantity} vote(s) were cast for <strong>{escape(contestant_name)}</strong> in {escape(contest_title)}.</p>",
        )
    except Exception:
        logging.getLogger(__name__).exception("Could not send vote notification email")


@transaction.atomic
def expire_vote_attempts(now=None):
    """Expire vote attempts left waiting for payment for more than 30 minutes."""
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=30)
    attempts = VoteAttempt.objects.select_for_update().filter(
        state=VoteAttempt.State.PAYMENT_PENDING,
        created_at__lte=cutoff,
    )
    count = 0
    for attempt in attempts:
        attempt.state = VoteAttempt.State.EXPIRED
        attempt.completed_at = now
        attempt.save(update_fields=["state", "completed_at"])
        AuditLog.objects.create(
            user=attempt.user,
            action_type=AuditLog.ActionType.VOTE_FAILED,
            resource_type="VoteAttempt",
            resource_id=str(attempt.pk),
            metadata={"reason": "payment_timeout"},
        )
        count += 1
    return count
