from datetime import datetime
from uuid import UUID

from ninja import Schema

from .models import Notification


class NotificationSchema(Schema):
    id: UUID
    title: str
    description: str
    time: datetime
    read: bool
    type: str

    @staticmethod
    def resolve_time(obj):
        return obj.created_at

    @staticmethod
    def resolve_read(obj):
        return obj.status == Notification.Status.READ

    @staticmethod
    def resolve_type(obj):
        title = obj.title.lower()
        if "vote" in title:
            return "vote"
        if "withdraw" in title or "payout" in title or "payment" in title:
            return "payment"
        if "ending" in title:
            return "warning"
        return "info"
