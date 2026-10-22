"""Vote limits and per-contest identity policy enforcement."""

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .models import VoterIdentity, VoterVerification, Vote, VotingPolicy


def get_voting_policy(contest):
    try:
        return contest.voting_policy
    except VotingPolicy.DoesNotExist:
        return None


def requires_verification(contest):
    policy = get_voting_policy(contest)
    return bool(policy and policy.verification_method != VotingPolicy.VerificationMethod.NONE)


def check_vote_limit(voter, contest, quantity):
    """Validate a requested quantity against the contest's voter limit."""
    if quantity < 1 or quantity > 1000:
        raise ValidationError({"quantity": "Vote quantity must be between 1 and 1000."})
    policy = get_voting_policy(contest)
    if not voter:
        if policy and not policy.allow_anonymous:
            raise ValidationError("This contest requires an authenticated voter.")
        return True
    if not voter.is_authenticated:
        if policy and not policy.allow_anonymous:
            raise ValidationError("This contest requires an authenticated voter.")
        return True
    if not policy or policy.vote_limit_type == VotingPolicy.VoteLimitType.UNLIMITED:
        return True

    if policy.vote_limit_type == VotingPolicy.VoteLimitType.ONE:
        limit = 1
    else:
        limit = policy.max_votes_per_voter
        if limit is None:
            raise ValidationError("The contest vote limit is not configured correctly.")

    prior_quantity = 0
    identity = VoterIdentity.objects.filter(user=voter, contest=contest).first()
    if identity and contest.source_poll_id:
        prior_quantity = Vote.objects.filter(
            poll_id=contest.source_poll_id, voter_identity=identity
        ).aggregate(total=Sum("vote_quantity"))["total"] or 0
    elif contest.source_poll_id:
        # Count historical votes created before identity linking.
        prior_quantity = Vote.objects.filter(
            poll_id=contest.source_poll_id, voter=voter
        ).aggregate(total=Sum("vote_quantity"))["total"] or 0

    if prior_quantity + quantity > limit:
        raise ValidationError({"quantity": f"This voter may cast at most {limit} vote(s) in this contest."})
    return True


def check_composite_verification(voter_identity, required_methods):
    """Return true only when every configured verification method succeeded."""
    required = set(required_methods or [])
    if len(required) < 2:
        raise ValidationError("Composite verification requires at least two methods.")
    successful = set(
        VoterVerification.objects.filter(
            voter_identity=voter_identity,
            status=VoterVerification.Status.SUCCESS,
            method__in=required,
        ).values_list("method", flat=True)
    )
    return verification_methods_satisfied(required, successful)


def verification_methods_satisfied(required_methods, successful_methods):
    """Return whether every configured verification method succeeded."""
    return set(required_methods or []) <= set(successful_methods or [])


def identity_status_allows_voting(status, expires_at=None, now=None):
    """Return whether an identity is verified and has not expired."""
    if status != VoterIdentity.VerificationStatus.VERIFIED:
        return False
    return expires_at is None or expires_at > (now or timezone.now())


def is_identity_verified(voter, contest):
    if not requires_verification(contest):
        return True
    identity = VoterIdentity.objects.filter(user=voter, contest=contest).first()
    if not identity:
        return False
    now = timezone.now()
    if not identity_status_allows_voting(
        identity.verification_status, identity.expires_at, now
    ):
        if (
            identity.verification_status == VoterIdentity.VerificationStatus.VERIFIED
            and identity.expires_at
            and identity.expires_at <= now
        ):
            identity.verification_status = VoterIdentity.VerificationStatus.EXPIRED
            identity.save(update_fields=["verification_status", "updated_at"])
        return False
    policy = get_voting_policy(contest)
    if policy and policy.verification_method == VotingPolicy.VerificationMethod.COMPOSITE:
        return check_composite_verification(identity, policy.required_verification_methods)
    return True
