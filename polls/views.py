from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Poll
from .serializers import PollSerializer
from django.db.models import Count
from contestants.models import Contestant

# Create your views here.

@api_view(["GET"])
def poll_list(request):
    polls = Poll.objects.filter(visibility="public", is_active=True).order_by("-created_at")
    serializer = PollSerializer(polls, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def poll_detail(request, slug):
    try:
        poll = Poll.objects.get(slug=slug, is_active=True)
    except Poll.DoesNotExist:
        return Response({"error": "Poll not found"}, status=404)

    serializer = PollSerializer(poll)
    return Response(serializer.data)




@api_view(["GET"])
def poll_results(request, slug):
    try:
        poll = Poll.objects.get(slug=slug)
    except Poll.DoesNotExist:
        return Response({"error": "Poll not found"}, status=404)

    results = Contestant.objects.filter(poll=poll).annotate(
        votes_count=Count("votes")
    ).order_by("-votes_count")

    data = [
        {
            "id": c.id,
            "name": c.name,
            "votes": c.votes_count
        }
        for c in results
    ]

    return Response({
        "poll": poll.title,
        "results": data
    })