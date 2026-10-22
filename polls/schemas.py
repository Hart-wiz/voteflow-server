from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from ninja import Field, Schema
from pydantic import ConfigDict


class ContestantSchema(Schema):
    id: UUID
    name: str
    author: str = ""
    description: str = ""
    image: str = ""
    votes: int = 0

    @staticmethod
    def resolve_image(obj):
        if not obj.image:
            return ""
        try:
            return obj.image.url
        except ValueError:
            return ""


class ContestantCreateSchema(Schema):
    name: str
    author: Optional[str] = ""
    description: Optional[str] = ""


class PollSchema(Schema):
    id: UUID
    slug: str
    title: str
    organizer: str = ""
    category: str = ""
    description: str = ""
    image: str = ""
    status: str
    endsAt: Optional[datetime] = None
    isPaid: bool = False
    pricePerVote: Decimal = Decimal(0)
    tags: list[str] = Field(default_factory=list)
    votesCount: int = 0
    votes: str = "0"
    endsIn: str = "—"
    createdAt: datetime
    contestants: list[ContestantSchema] = Field(default_factory=list)

    @staticmethod
    def resolve_image(obj):
        if not obj.image:
            return ""
        try:
            return obj.image.url
        except ValueError:
            return ""

    @staticmethod
    def resolve_endsAt(obj):
        return obj.ends_at

    @staticmethod
    def resolve_isPaid(obj):
        return obj.is_paid

    @staticmethod
    def resolve_pricePerVote(obj):
        return obj.price_per_vote

    @staticmethod
    def resolve_votesCount(obj):
        if hasattr(obj, "annotated_votes_count"):
            return obj.annotated_votes_count or 0
        return obj.votes_count

    @staticmethod
    def resolve_votes(obj):
        count = PollSchema.resolve_votesCount(obj)
        return f"{count:,}"

    @staticmethod
    def resolve_endsIn(obj):
        if not obj.ends_at:
            return "—"
        from django.utils import timezone

        remaining = obj.ends_at - timezone.now()
        seconds = max(0, int(remaining.total_seconds()))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes = seconds // 60
        if days:
            return f"{days}d"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    @staticmethod
    def resolve_createdAt(obj):
        return obj.created_at


class PollCreateSchema(Schema):
    model_config = ConfigDict(populate_by_name=True)

    title: str
    organizer: Optional[str] = None
    category: Optional[str] = ""
    description: Optional[str] = ""
    status: str = "new"
    ends_at: Optional[datetime] = Field(default=None, alias="endsAt")
    is_paid: bool = Field(default=False, alias="isPaid")
    price_per_vote: Decimal = Field(default=Decimal(0), alias="pricePerVote")


class PollUpdateSchema(Schema):
    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = None
    organizer: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    ends_at: Optional[datetime] = Field(default=None, alias="endsAt")
    is_paid: Optional[bool] = Field(default=None, alias="isPaid")
    price_per_vote: Optional[Decimal] = Field(default=None, alias="pricePerVote")
    tags: Optional[list[str]] = None


class VoteSchema(Schema):
    contestant_id: UUID
    quantity: int = Field(default=1, ge=1, le=1000)
    email: Optional[str] = ""
    payment_ref: Optional[str] = ""
