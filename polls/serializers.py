from rest_framework import serializers
from .models import Poll
from contestants.models import Contestant


class ContestantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contestant
        fields = ["id", "name", "image"]


class PollSerializer(serializers.ModelSerializer):
    contestants = ContestantSerializer(many=True, read_only=True)

    class Meta:
        model = Poll
        fields = [
            "id",
            "title",
            "description",
            "slug",
            "vote_type",
            "visibility",
            "starts_at",
            "ends_at",
            "contestants",
            "created_at",
        ]