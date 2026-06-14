from rest_framework.decorators import api_view
from rest_framework.response import Response
from polls.models import Poll
from contestants.models import Contestant
from .services import create_vote, is_rate_limited, has_already_voted
from .models import VoteAuditLog


@api_view(["POST"])
def cast_vote(request):
    poll_id = request.data.get("poll_id")
    contestant_id = request.data.get("contestant_id")

    poll = Poll.objects.get(id=poll_id)
    contestant = Contestant.objects.get(id=contestant_id)

    ip = request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT")

    # 1. LOG ATTEMPT
    VoteAuditLog.objects.create(
        poll=poll,
        ip_address=ip,
        user_agent=user_agent,
        action="vote_attempt"
    )

    # 2. RATE LIMIT CHECK (anti spam)
    if is_rate_limited(ip, poll):
        VoteAuditLog.objects.create(
            poll=poll,
            ip_address=ip,
            user_agent=user_agent,
            action="vote_blocked"
        )
        return Response(
            {"error": "Too many votes. Please slow down."},
            status=429
        )

    # 3. DUPLICATE VOTE CHECK (logged-in users)
    if has_already_voted(request.user, poll):
        VoteAuditLog.objects.create(
            poll=poll,
            ip_address=ip,
            user_agent=user_agent,
            action="vote_blocked"
        )
        return Response(
            {"error": "You already voted on this poll."},
            status=400
        )

    # 4. CREATE VOTE
    vote = create_vote(
        poll=poll,
        contestant=contestant,
        voter=request.user if request.user.is_authenticated else None,
        voter_identifier=request.data.get("identifier"),
        ip=ip,
        user_agent=user_agent,
    )

    # 5. LOG SUCCESS
    VoteAuditLog.objects.create(
        poll=poll,
        ip_address=ip,
        user_agent=user_agent,
        action="vote_success"
    )

    return Response({
        "message": "Vote recorded successfully",
        "vote_id": vote.id
    })