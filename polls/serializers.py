"""
Serializers for the polls app.

Handles serialization of Polls and Contestants with camelCase field names
to match the frontend TypeScript interfaces exactly.

Frontend Poll shape:
    { id, slug, title, organizer, category, description, image, status,
      endsAt, isPaid, pricePerVote, tags, votesCount, contestants }

Frontend Contestant shape:
    { id, name, author, description, image, votes }
"""

from rest_framework import serializers
from django.db.models import Sum

from .models import Poll, Contestant


# ---------------------------------------------------------------------------
# Contestant Serializers
# ---------------------------------------------------------------------------

class ContestantSerializer(serializers.ModelSerializer):
    """
    Full contestant representation.
    Used inside both PollListSerializer and PollDetailSerializer.
    """

    class Meta:
        model = Contestant
        fields = ["id", "name", "author", "description", "image", "votes"]
        read_only_fields = ["id", "votes"]


class ContestantCreateSerializer(serializers.ModelSerializer):
    """
    Used when creating contestants as part of poll creation.
    The poll FK is set by the view, not by the client.
    """

    class Meta:
        model = Contestant
        fields = ["name", "author", "description", "image"]


# ---------------------------------------------------------------------------
# Poll Serializers
# ---------------------------------------------------------------------------

class PollListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for GET /polls/ (list view).
    Includes votesCount as an annotation and nested contestants.
    """
    # camelCase mappings
    endsAt = serializers.DateTimeField(source="ends_at", required=False, allow_null=True)
    isPaid = serializers.BooleanField(source="is_paid", read_only=True)
    pricePerVote = serializers.DecimalField(
        source="price_per_vote", max_digits=10, decimal_places=2, read_only=True
    )
    votesCount = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    contestants = ContestantSerializer(many=True, read_only=True)

    class Meta:
        model = Poll
        fields = [
            "id", "slug", "title", "organizer", "category", "description",
            "image", "status", "endsAt", "isPaid", "pricePerVote", "tags",
            "votesCount", "contestants", "createdAt",
        ]

    def get_votesCount(self, obj):
        """
        Use annotated value if available (from queryset), else fall back to property.
        """
        if hasattr(obj, "annotated_votes_count"):
            return obj.annotated_votes_count or 0
        return obj.votes_count


class PollDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for GET /polls/<slug>/ (detail view).
    Includes all fields and full contestant data.
    """
    endsAt = serializers.DateTimeField(source="ends_at", required=False, allow_null=True)
    isPaid = serializers.BooleanField(source="is_paid", read_only=True)
    pricePerVote = serializers.DecimalField(
        source="price_per_vote", max_digits=10, decimal_places=2, read_only=True
    )
    votesCount = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    contestants = ContestantSerializer(many=True, read_only=True)

    class Meta:
        model = Poll
        fields = [
            "id", "slug", "title", "organizer", "category", "description",
            "image", "status", "endsAt", "isPaid", "pricePerVote", "tags",
            "votesCount", "contestants", "createdAt",
        ]

    def get_votesCount(self, obj):
        if hasattr(obj, "annotated_votes_count"):
            return obj.annotated_votes_count or 0
        return obj.votes_count


class PollCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for POST /polls/ and PATCH /polls/<slug>/.
    Accepts multipart/form-data (for image upload).

    The creator is set automatically by the view, not the client.
    """
    # Accept camelCase from frontend, map to snake_case model fields
    endsAt = serializers.DateTimeField(source="ends_at", required=False, allow_null=True)
    isPaid = serializers.BooleanField(source="is_paid", required=False, default=False)
    pricePerVote = serializers.DecimalField(
        source="price_per_vote", max_digits=10, decimal_places=2, required=False
    )
    contestants = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = Poll
        fields = [
            "title", "organizer", "category", "description", "image",
            "status", "endsAt", "isPaid", "pricePerVote", "tags",
            "contestants",
        ]

    def create(self, validated_data):
        import json
        import re
        
        contestants_data = validated_data.pop("contestants", [])
        
        # 1. Parse if sent as a JSON string
        if isinstance(contestants_data, str):
            try:
                contestants_data = json.loads(contestants_data)
            except Exception:
                contestants_data = []

        # 2. If empty, check initial_data for form-data array structures
        if not contestants_data and hasattr(self, 'initial_data'):
            parsed_contestants = {}
            for key, value in self.initial_data.items():
                match = re.match(r'^contestants\[(\d+)\](?:\[([a-zA-Z0-9_]+)\]|\.([a-zA-Z0-9_]+))$', key)
                if match:
                    idx = int(match.group(1))
                    field = match.group(2) or match.group(3)
                    if idx not in parsed_contestants:
                        parsed_contestants[idx] = {}
                    parsed_contestants[idx][field] = value
            if parsed_contestants:
                contestants_data = [parsed_contestants[i] for i in sorted(parsed_contestants.keys())]

        poll = super().create(validated_data)

        # Create contestants
        if isinstance(contestants_data, list):
            for c_data in contestants_data:
                valid_fields = ["name", "author", "description"]
                clean_data = {k: v for k, v in c_data.items() if k in valid_fields}
                if clean_data.get("name"):
                    Contestant.objects.create(poll=poll, **clean_data)

        return poll

    def update(self, instance, validated_data):
        import json
        import re
        
        contestants_data = validated_data.pop("contestants", None)
        
        if isinstance(contestants_data, str):
            try:
                contestants_data = json.loads(contestants_data)
            except Exception:
                contestants_data = None

        if not contestants_data and hasattr(self, 'initial_data'):
            parsed_contestants = {}
            for key, value in self.initial_data.items():
                match = re.match(r'^contestants\[(\d+)\](?:\[([a-zA-Z0-9_]+)\]|\.([a-zA-Z0-9_]+))$', key)
                if match:
                    idx = int(match.group(1))
                    field = match.group(2) or match.group(3)
                    if idx not in parsed_contestants:
                        parsed_contestants[idx] = {}
                    parsed_contestants[idx][field] = value
            if parsed_contestants:
                contestants_data = [parsed_contestants[i] for i in sorted(parsed_contestants.keys())]

        instance = super().update(instance, validated_data)

        if isinstance(contestants_data, list):
            for c_data in contestants_data:
                valid_fields = ["name", "author", "description"]
                clean_data = {k: v for k, v in c_data.items() if k in valid_fields}
                if clean_data.get("name") and 'id' not in c_data:
                    Contestant.objects.create(poll=instance, **clean_data)

        return instance

    def to_representation(self, instance):
        """Return the full poll detail after create/update."""
        return PollDetailSerializer(instance).data


# ---------------------------------------------------------------------------
# Vote Serializer (for POST /polls/<slug>/vote/)
# ---------------------------------------------------------------------------

class VoteSerializer(serializers.Serializer):
    """
    Validates the vote payload.

    Payload:
        {
            "contestant_id": "uuid",
            "quantity": 1,
            "email": "voter@example.com",
            "payment_ref": "paystack_txn_ref_123"  // only for paid polls
        }
    """
    contestant_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    email = serializers.EmailField(required=False, allow_blank=True)
    payment_ref = serializers.CharField(required=False, allow_blank=True)