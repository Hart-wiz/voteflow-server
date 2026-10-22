"""Authentication and account endpoints exposed to VoteFlow Client."""

import html
import hashlib
import secrets
from datetime import timedelta
from datetime import datetime

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken
from pydantic import EmailStr

from notifications.email import send_transactional_email
from .permissions import require_role
from voting.audit import create_audit_log
from voting.models import AuditLog

from .models import OrganizerProfile, User, UserOTP
from .services import (
    approve_organizer_request as approve_organizer_request_service,
    reject_organizer_request as reject_organizer_request_service,
    request_organizer_privileges as request_organizer_privileges_service,
)
from .schemas import (
    AuthResponseSchema,
    LoginSchema,
    LogoutSchema,
    MeUpdateSchema,
    RegisterSchema,
    ResetPasswordSchema,
    TokenPairSchema,
    UserSchema,
)

router = Router(tags=["Auth"])


class ResetPasswordConfirmSchema(Schema):
    email: EmailStr
    code: str
    password: str


class RefreshSchema(Schema):
    refresh: str


class OrganizerRequestSchema(Schema):
    business_name: str = ""
    bio: str = ""


class OrganizerProfileSchema(Schema):
    id: str
    name: str
    email: str
    business_name: str
    bio: str
    is_approved: bool
    requested_at: datetime

    @staticmethod
    def resolve_name(obj):
        return obj.user.name

    @staticmethod
    def resolve_email(obj):
        return obj.user.email


@router.post("/register/", response={201: AuthResponseSchema})
def register(request, payload: RegisterSchema):
    try:
        user = User.objects.create_user(
            email=payload.email,
            name=payload.name,
            password=payload.password,
        )
    except IntegrityError as exc:
        raise HttpError(400, "User with this email already exists.") from exc

    if payload.organization and payload.organization.strip():
        request_organizer_privileges_service(user, business_name=payload.organization)

    refresh = RefreshToken.for_user(user)
    return 201, {
        "user": user,
        "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)},
    }


@router.post("/login/", response={200: AuthResponseSchema})
def login(request, payload: LoginSchema):
    user = User.objects.filter(email=payload.email).first()
    if not user or not user.check_password(payload.password):
        email_digest = hashlib.sha256(payload.email.lower().encode("utf-8")).hexdigest()
        create_audit_log(
            action_type=AuditLog.ActionType.LOGIN_FAILED,
            user=user,
            resource_type="Authentication",
            resource_id=email_digest,
            request=request,
            metadata={"method": "password"},
        )
        raise HttpError(400, "Invalid email or password")
    if not user.is_active:
        create_audit_log(
            action_type=AuditLog.ActionType.LOGIN_FAILED,
            user=user,
            resource_type="Authentication",
            resource_id=str(user.pk),
            request=request,
            metadata={"method": "password", "reason": "inactive_account"},
        )
        raise HttpError(400, "This account has been deactivated")

    refresh = RefreshToken.for_user(user)
    create_audit_log(
        action_type=AuditLog.ActionType.LOGIN_SUCCESS,
        user=user,
        resource_type="Authentication",
        resource_id=str(user.pk),
        request=request,
        metadata={"method": "password"},
    )
    return {
        "user": user,
        "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)},
    }


@router.post("/logout/", response={200: dict})
def logout(request, payload: LogoutSchema):
    try:
        token = RefreshToken(payload.refresh)
        user = User.objects.filter(pk=token.get("user_id")).first()
        token.blacklist()
    except TokenError as exc:
        raise HttpError(400, "Token is invalid or blacklisted") from exc
    create_audit_log(
        action_type=AuditLog.ActionType.LOGOUT,
        user=user,
        resource_type="Authentication",
        resource_id=str(user.pk) if user else "unknown",
        request=request,
        metadata={"method": "refresh_token"},
    )
    return {"success": True, "message": "Logged out successfully."}


@router.post("/token/refresh/", response={200: TokenPairSchema})
def refresh_token(request, payload: RefreshSchema):
    try:
        old_refresh = RefreshToken(payload.refresh)
        user = User.objects.get(pk=old_refresh["user_id"], is_active=True)
    except (TokenError, User.DoesNotExist, KeyError) as exc:
        raise HttpError(401, "Refresh token is invalid or expired.") from exc

    old_refresh.blacklist()
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@router.post("/password/reset/", response={200: dict})
def send_reset_code(request, payload: ResetPasswordSchema):
    user = User.objects.filter(email=payload.email).first()
    # Keep the response identical for known and unknown addresses.
    if user:
        otp_profile, _created = UserOTP.objects.get_or_create(user=user)
        otp_profile.otp_code = f"{secrets.randbelow(900000) + 100000}"
        otp_profile.save(update_fields=["otp_code", "updated_at"])
        safe_name = html.escape(user.name)
        code = otp_profile.otp_code
        send_transactional_email(
            to=user.email,
            subject="Reset your VoteFlow password",
            text=f"Hi {user.name}, your password reset code is {code}. It expires in 10 minutes.",
            html=f"<p>Hi {safe_name},</p><p>Your password reset code is <strong>{code}</strong>.</p><p>It expires in 10 minutes.</p>",
        )
    return {"success": True, "message": "If the account exists, a reset code has been sent."}


@router.post("/password/reset/confirm/", response={200: dict})
def confirm_password_reset(request, payload: ResetPasswordConfirmSchema):
    user = User.objects.filter(email=payload.email).first()
    otp_profile = UserOTP.objects.filter(user=user).first() if user else None
    if (
        not user
        or not otp_profile
        or not secrets.compare_digest(otp_profile.otp_code, payload.code)
        or timezone.now() - otp_profile.updated_at > timedelta(minutes=10)
    ):
        raise HttpError(400, "The reset code is invalid or expired.")

    try:
        validate_password(payload.password, user)
    except ValidationError as exc:
        raise HttpError(400, " ".join(exc.messages)) from exc

    user.set_password(payload.password)
    user.save(update_fields=["password", "updated_at"])
    otp_profile.delete()
    return {"success": True, "message": "Password reset successfully."}


@router.get("/me/", response={200: UserSchema}, auth=JWTAuth())
def get_me(request):
    return request.user


@router.patch("/me/", response={200: UserSchema}, auth=JWTAuth())
def update_me(request, payload: MeUpdateSchema):
    user = request.user
    changes = payload.model_dump(exclude_unset=True, exclude_none=True, by_alias=True)
    if "avatarUrl" in changes:
        user.avatar_url = changes.pop("avatarUrl")
    for field, value in changes.items():
        setattr(user, field, value)
    user.save()
    return user


@router.get("/organizer/request/", response={200: OrganizerProfileSchema | dict}, auth=JWTAuth())
def organizer_request_status(request):
    profile = OrganizerProfile.objects.select_related("user").filter(user=request.user).first()
    if not profile:
        return {"status": "not_requested"}
    return profile


@router.post("/organizer/request/", response={200: dict, 201: OrganizerProfileSchema}, auth=JWTAuth())
def request_organizer_privileges(request, payload: OrganizerRequestSchema):
    if request.user.role in (User.Role.ORGANIZER, User.Role.ADMIN):
        return {"status": "approved", "message": "Organizer access is already active."}
    profile, created = request_organizer_privileges_service(
        request.user,
        business_name=payload.business_name,
        bio=payload.bio,
    )
    if profile is None:
        return {"status": "approved", "message": "Organizer access is already active."}
    return (201 if created else 200), {
        "id": str(profile.id),
        "name": profile.user.name,
        "email": profile.user.email,
        "business_name": profile.business_name,
        "bio": profile.bio,
        "is_approved": profile.is_approved,
        "requested_at": profile.requested_at,
        "status": "approved" if profile.is_approved else "pending",
        "message": "Organizer request submitted for admin review.",
    }


@router.get("/admin/organizers/", response=list[OrganizerProfileSchema], auth=JWTAuth())
@require_role(User.Role.ADMIN)
def list_organizer_requests(request):
    return OrganizerProfile.objects.select_related("user").filter(is_approved=False).order_by("requested_at")


@router.post("/admin/organizers/{profile_id}/approve/", response={200: dict}, auth=JWTAuth())
@require_role(User.Role.ADMIN)
def approve_organizer_request(request, profile_id: str):
    try:
        profile, changed = approve_organizer_request_service(request.user, profile_id)
    except OrganizerProfile.DoesNotExist as exc:
        raise HttpError(404, "Organizer request not found.") from exc
    if not changed:
        return {"success": True, "message": "Organizer request was already approved."}

    return {"success": True, "message": "Organizer request approved."}


@router.post("/admin/organizers/{profile_id}/reject/", response={200: dict}, auth=JWTAuth())
@require_role(User.Role.ADMIN)
def reject_organizer_request_endpoint(request, profile_id: str):
    rejected = reject_organizer_request_service(request.user, profile_id)
    if not rejected:
        raise HttpError(404, "Organizer request not found.")
    return {"success": True, "message": "Organizer request rejected."}
