"""Vote-attempt and identity-verification endpoints."""

from typing import Optional

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja_jwt.authentication import JWTAuth
from pydantic import Field

from polls.models import Contest
from polls.models import Contestant

from .models import VoteAttempt, VoterIdentity, VoterVerification, VotingPolicy
from .policies import get_voting_policy
from .providers import verify_voter_identity
from .services import commit_vote, initiate_vote_attempt, progress_vote_attempt

router = Router(tags=["Voting"])
verification_router = Router(tags=["Voter Verification"])


class VoteInitiateSchema(Schema):
    contest_id: str
    contestant_id: str
    quantity: int = 1


class VoteAttemptSchema(Schema):
    id: str
    contest_id: str
    contestant_id: str
    state: str
    vote_quantity: int
    rejection_reason: str
    created_at: str
    completed_at: Optional[str]


class AttemptReferenceSchema(Schema):
    attempt_id: str


class VerificationSchema(Schema):
    contest_id: str
    verification_id: Optional[str] = None
    attempt_id: Optional[str] = None
    method: Optional[str] = None
    action: str = "start"
    data: dict = Field(default_factory=dict)


class VotePaymentSchema(Schema):
    attempt_id: str


class VoteCommitSchema(Schema):
    attempt_id: str
    payment_id: Optional[str] = None


class VerificationStatusSchema(Schema):
    contest_id: str
    status: str
    verified_at: Optional[str]
    methods: list[dict]


def _serialize_attempt(attempt):
    return {
        "id": str(attempt.pk),
        "contest_id": str(attempt.contest_id),
        "contestant_id": str(attempt.contestant_id),
        "state": attempt.state,
        "vote_quantity": attempt.vote_quantity,
        "rejection_reason": attempt.rejection_reason,
        "created_at": attempt.created_at.isoformat(),
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
    }


@router.post("/initiate/", response={201: VoteAttemptSchema}, auth=JWTAuth())
def initiate(request, payload: VoteInitiateSchema):
    contest = get_object_or_404(Contest, pk=payload.contest_id)
    if not contest.source_poll_id:
        raise ValidationError("This contest has no contestant data.")
    contestant = get_object_or_404(
        Contestant,
        pk=payload.contestant_id,
        poll_id=contest.source_poll_id,
    )
    attempt = initiate_vote_attempt(request.user, contest, contestant, payload.quantity, request)
    return 201, _serialize_attempt(attempt)


@router.post("/verify/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify(request, payload: VerificationSchema):
    attempt = get_object_or_404(
        VoteAttempt.objects.select_related("contest", "user"),
        pk=payload.attempt_id or "",
        user=request.user,
        state=VoteAttempt.State.IDENTITY_CHECK,
    )
    method = payload.method
    if not method:
        policy = get_voting_policy(attempt.contest)
        method = policy.verification_method if policy else VotingPolicy.VerificationMethod.NONE
    verification_id = payload.verification_id
    verification = None
    if payload.action == "complete":
        verification = get_object_or_404(
            VoterVerification.objects.select_related("voter_identity"),
            pk=verification_id,
            voter_identity__user=request.user,
            voter_identity__contest=attempt.contest,
        )
    result = verify_voter_identity(
        request.user,
        attempt.contest,
        method,
        payload.data,
        verification=verification,
        complete=payload.action == "complete",
    )
    identity = VoterIdentity.objects.get(user=request.user, contest=attempt.contest)
    if identity.verification_status == VoterIdentity.VerificationStatus.VERIFIED:
        attempt = progress_vote_attempt(
            attempt,
            VoteAttempt.State.VERIFIED,
            context={"verified_at": identity.verified_at.isoformat() if identity.verified_at else ""},
        )
    return {
        "verification_id": str(result.pk),
        "verification_status": result.status,
        "identity_status": identity.verification_status,
        "attempt": _serialize_attempt(attempt),
    }


@router.post("/payment/", response={200: dict}, auth=JWTAuth())
def create_vote_payment(request, payload: VotePaymentSchema):
    attempt = get_object_or_404(VoteAttempt, pk=payload.attempt_id, user=request.user)
    if attempt.state != VoteAttempt.State.VERIFIED:
        raise ValidationError("Verify your identity before starting payment.")
    from payments.services import initialize_vote_payment

    payment, authorization_url = initialize_vote_payment(attempt)
    return {
        "payment_id": str(payment.pk),
        "reference": payment.provider_reference,
        "authorization_url": authorization_url,
        "amount": str(payment.total_amount),
        "currency": payment.currency,
    }


@router.post("/commit/", response={200: dict}, auth=JWTAuth())
def commit(request, payload: VoteCommitSchema):
    attempt = get_object_or_404(VoteAttempt, pk=payload.attempt_id, user=request.user)
    payment = None
    if payload.payment_id:
        from payments.models import Payment

        payment = get_object_or_404(Payment, pk=payload.payment_id, vote_attempt=attempt)
    votes = commit_vote(attempt, payment)
    return {
        "success": True,
        "attempt_id": str(attempt.pk),
        "votes_created": len(votes),
        "vote_numbers": [vote.vote_number for vote in votes],
    }


@router.get("/attempt/{attempt_id}/", response=VoteAttemptSchema, auth=JWTAuth())
def get_attempt(request, attempt_id: str):
    attempt = get_object_or_404(
        VoteAttempt.objects.select_related("contest", "contestant"),
        pk=attempt_id,
        user=request.user,
    )
    return _serialize_attempt(attempt)


def _verification_endpoint(request, payload, method):
    contest = get_object_or_404(Contest, pk=payload.contest_id)
    identity, _ = VoterIdentity.objects.get_or_create(user=request.user, contest=contest)
    verification = None
    if payload.action == "complete":
        verification = get_object_or_404(
            VoterVerification.objects.select_related("voter_identity"),
            pk=payload.verification_id,
            voter_identity=identity,
            method=method,
        )
    result = verify_voter_identity(
        request.user,
        contest,
        method,
        payload.data,
        verification=verification,
        complete=payload.action == "complete",
    )
    identity.refresh_from_db()
    return {
        "verification_id": str(result.pk),
        "status": result.status,
        "identity_status": identity.verification_status,
    }


@verification_router.post("/email/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify_email(request, payload: VerificationSchema):
    return _verification_endpoint(request, payload, VotingPolicy.VerificationMethod.EMAIL)


@verification_router.post("/phone/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify_phone(request, payload: VerificationSchema):
    return _verification_endpoint(request, payload, VotingPolicy.VerificationMethod.PHONE)


@verification_router.post("/nin/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify_nin(request, payload: VerificationSchema):
    return _verification_endpoint(request, payload, VotingPolicy.VerificationMethod.NIN)


@verification_router.post("/voters-card/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify_voters_card(request, payload: VerificationSchema):
    return _verification_endpoint(request, payload, VotingPolicy.VerificationMethod.VOTERS_CARD)


@verification_router.post("/fingerprint/", response={200: dict, 201: dict}, auth=JWTAuth())
def verify_fingerprint(request, payload: VerificationSchema):
    return _verification_endpoint(request, payload, VotingPolicy.VerificationMethod.FINGERPRINT)


@verification_router.get("/status/{contest_id}/", response=VerificationStatusSchema, auth=JWTAuth())
def verification_status(request, contest_id: str):
    contest = get_object_or_404(Contest, pk=contest_id)
    identity = VoterIdentity.objects.filter(user=request.user, contest=contest).first()
    if not identity:
        return {
            "contest_id": str(contest.pk),
            "status": VoterIdentity.VerificationStatus.UNVERIFIED,
            "verified_at": None,
            "methods": [],
        }
    methods = list(
        identity.verification_attempts.order_by("-created_at").values(
            "method", "provider", "status", "created_at", "completed_at"
        )
    )
    for method in methods:
        method["created_at"] = method["created_at"].isoformat()
        method["completed_at"] = method["completed_at"].isoformat() if method["completed_at"] else None
    return {
        "contest_id": str(contest.pk),
        "status": identity.verification_status,
        "verified_at": identity.verified_at.isoformat() if identity.verified_at else None,
        "methods": methods,
    }
