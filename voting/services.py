"""
Voting service layer.

Provides vote creation, rate limiting, and duplicate vote prevention.
Business logic lives here; views call these functions.
"""

from datetime import timedelta
from django.utils import timezone

from .models import Vote


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
):
    """
    Create a Vote record.

    Args:
        poll:           Poll instance
        contestant:     Contestant instance
        voter:          User instance (None for anonymous voters)
        voter_email:    Email string for anonymous voters
        quantity:       Number of votes (>=1)
        payment_ref:    Paystack transaction reference (paid polls only)
        ip:             Voter's IP address
        user_agent:     Voter's browser user agent
        is_paid:        Whether this is a paid vote
        amount:         Total payment amount (Decimal)

    Returns:
        Vote instance
    """
    vote = Vote.objects.create(
        poll=poll,
        contestant=contestant,
        voter=voter,
        voter_email=voter_email,
        quantity=quantity,
        payment_ref=payment_ref,
        ip_address=ip,
        user_agent=user_agent,
        is_paid=is_paid,
        amount=amount,
    )
    return vote


def is_rate_limited(ip, poll):
    """
    Basic rate limiting: max 3 votes per IP per poll within 10 seconds.
    Returns True if the voter should be blocked.
    """
    time_limit = timezone.now() - timedelta(seconds=10)
    recent_votes = Vote.objects.filter(
        ip_address=ip,
        poll=poll,
        created_at__gte=time_limit,
    ).count()
    return recent_votes >= 3


def has_already_voted(user, poll):
    """
    Check if an authenticated user has already voted on this poll.
    Returns False for anonymous users.
    """
    if not user or not user.is_authenticated:
        return False
    return Vote.objects.filter(voter=user, poll=poll).exists()