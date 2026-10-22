from uuid import UUID

from django.shortcuts import get_object_or_404
from ninja import Router
from ninja_jwt.authentication import JWTAuth

from .models import Notification
from .schemas import NotificationSchema

router = Router(tags=["Notifications"])


@router.get("/", response=list[NotificationSchema], auth=JWTAuth())
def list_notifications(request):
    return Notification.objects.filter(receiver=request.user).order_by("-created_at")


@router.post("/read-all/", response={200: dict}, auth=JWTAuth())
def mark_all_read(request):
    Notification.objects.filter(
        receiver=request.user,
        status=Notification.Status.DELIVERED,
    ).update(status=Notification.Status.READ)
    return {"success": True}


@router.post("/{notification_id}/read/", response={200: dict}, auth=JWTAuth())
def mark_read(request, notification_id: UUID):
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        receiver=request.user,
    )
    if notification.status != Notification.Status.READ:
        notification.status = Notification.Status.READ
        notification.save(update_fields=["status", "updated_at"])
    return {"success": True}
