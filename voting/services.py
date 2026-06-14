from .models import Vote
from django.utils import timezone
from datetime import timedelta
from .models import Vote


def create_vote(*, poll, contestant, voter=None, voter_identifier=None, ip=None, user_agent=None, is_paid=False, amount=0):
    vote = Vote.objects.create(
        poll=poll,
        contestant=contestant,
        voter=voter,
        voter_identifier=voter_identifier,
        ip_address=ip,
        user_agent=user_agent,
        is_paid=is_paid,
        amount=amount
    )

    return vote


#  Basic Rate Limiting 
def is_rate_limited(ip, poll):
    time_limit = timezone.now() - timedelta(seconds=10)

    recent_votes = Vote.objects.filter(
        ip_address=ip,
        poll=poll,
        created_at__gte=time_limit
    ).count()

    return recent_votes >= 3

# Duplicate Vote Prevention Rules

def has_already_voted(user, poll):
    if not user:
        return False

    return Vote.objects.filter(
        voter=user,
        poll=poll
    ).exists()