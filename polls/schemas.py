from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import List, Optional

from ninja import ModelSchema, Schema, Field
from .models import Poll, Contestant

# -------------------------------------------------------------------
# Contestant Schemas
# -------------------------------------------------------------------

class ContestantSchema(ModelSchema):
    class Meta:
        model = Contestant
        fields = ("id", "name", "author", "description", "image", "votes")

class ContestantCreateSchema(Schema):
    name: str
    author: Optional[str] = ""
    description: Optional[str] = ""
    # image will be handled by File in the api.py if needed, 
    # but for nested creation we might just take these fields.

# -------------------------------------------------------------------
# Poll Schemas
# -------------------------------------------------------------------

class PollSchema(ModelSchema):
    endsAt: Optional[datetime] = Field(None, alias="ends_at")
    isPaid: bool = Field(False, alias="is_paid")
    pricePerVote: Decimal = Field(Decimal(0), alias="price_per_vote")
    votesCount: int = Field(0, alias="votes_count")
    createdAt: datetime = Field(..., alias="created_at")
    contestants: List[ContestantSchema]

    class Meta:
        model = Poll
        fields = (
            "id", "slug", "title", "organizer", "category", "description",
            "image", "status", "tags",
        )

    @staticmethod
    def resolve_votesCount(obj):
        if hasattr(obj, "annotated_votes_count"):
            return obj.annotated_votes_count or 0
        return obj.votes_count

class PollCreateSchema(Schema):
    title: str
    organizer: Optional[str] = None
    category: Optional[str] = ""
    description: Optional[str] = ""
    status: str = "new"
    endsAt: Optional[datetime] = None
    isPaid: bool = False
    pricePerVote: Decimal = Decimal(0)
    tags: List[str] = []
    # contestants: Optional[List[ContestantCreateSchema]] = None

class PollUpdateSchema(Schema):
    title: Optional[str] = None
    organizer: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    endsAt: Optional[datetime] = None
    isPaid: Optional[bool] = None
    pricePerVote: Optional[Decimal] = None
    tags: Optional[List[str]] = None

# -------------------------------------------------------------------
# Vote Schema
# -------------------------------------------------------------------

class VoteSchema(Schema):
    contestant_id: UUID
    quantity: int = 1
    email: Optional[str] = ""
    payment_ref: Optional[str] = ""
