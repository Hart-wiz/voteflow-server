"""Administrator-only user, audit, and contest moderation APIs."""

import uuid
from datetime import datetime
from typing import Optional

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.pagination import paginate
from ninja_jwt.authentication import JWTAuth

from accounts.models import User
from accounts.permissions import require_role
from polls.models import Contest
from polls.services import suspend_contest
from voting.models import AuditLog

router = Router(tags=["Administration"])


class RoleUpdateSchema(Schema):
    role: str


class SuspendContestSchema(Schema):
    reason: str = ""


class AdminUserSchema(Schema):
    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime


class AuditLogSchema(Schema):
    id: uuid.UUID
    action_type: str
    resource_type: str
    resource_id: str
    user_id: Optional[uuid.UUID]
    timestamp: datetime
    ip_hash: str
    device_fingerprint: str
    metadata: dict


@router.get("/users/", response=list[AdminUserSchema], auth=JWTAuth())
@require_role(User.Role.ADMIN)
@paginate
def list_users(request, role: Optional[str] = None, search: Optional[str] = None):
    queryset = User.objects.all().order_by("-created_at")
    if role:
        queryset = queryset.filter(role=role)
    if search:
        queryset = queryset.filter(Q(email__icontains=search) | Q(name__icontains=search))
    return queryset


@router.patch("/users/{user_id}/role/", response={200: dict}, auth=JWTAuth())
@require_role(User.Role.ADMIN)
def update_user_role(request, user_id: str, payload: RoleUpdateSchema):
    if payload.role not in User.Role.values:
        raise ValidationError({"role": "Choose USER, ORGANIZER, or ADMIN."})
    user = get_object_or_404(User, pk=user_id)
    if user.pk == request.user.pk and payload.role != User.Role.ADMIN:
        active_admins = User.objects.filter(role=User.Role.ADMIN, is_active=True).count()
        if active_admins <= 1:
            raise ValidationError("The last active administrator cannot demote itself.")
    previous = user.role
    user.role = payload.role
    user.save(update_fields=["role", "updated_at"])
    AuditLog.objects.create(
        user=request.user,
        action_type=AuditLog.ActionType.ROLE_CHANGE,
        resource_type="User",
        resource_id=str(user.pk),
        metadata={"target_user_id": str(user.pk), "old_role": previous, "new_role": user.role},
    )
    return {"success": True, "user_id": str(user.pk), "old_role": previous, "role": user.role}


@router.get("/audit-logs/", response=list[AuditLogSchema], auth=JWTAuth())
@require_role(User.Role.ADMIN)
@paginate
def list_audit_logs(
    request,
    action_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[str] = None,
):
    queryset = AuditLog.objects.select_related("user").order_by("-timestamp")
    if action_type:
        queryset = queryset.filter(action_type=action_type)
    if resource_type:
        queryset = queryset.filter(resource_type=resource_type)
    if user_id:
        queryset = queryset.filter(user_id=user_id)
    return queryset


@router.post("/contests/{slug}/suspend/", response={200: dict}, auth=JWTAuth())
@require_role(User.Role.ADMIN)
def suspend(request, slug: str, payload: SuspendContestSchema):
    contest = get_object_or_404(Contest, slug=slug)
    contest = suspend_contest(contest, request.user, payload.reason)
    return {"success": True, "contest_id": str(contest.pk), "state": contest.state}
