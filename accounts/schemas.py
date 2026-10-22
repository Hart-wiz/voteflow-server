from datetime import datetime

from ninja import ModelSchema, Schema
from pydantic import EmailStr

from .models import User  # Direct import keeps Pylance & Ninja happy

# -------------------------------------------------------------------
# Output Schemas (Responses)
# -------------------------------------------------------------------


class UserSchema(ModelSchema):
    """
    Read-only representation of a User.
    Serialized camelCase fields match frontend expectations.
    """

    avatarUrl: str | None = None
    createdAt: datetime
    isCreator: bool = False
    role: str = "user"

    class Meta:
        model = User
        fields = ("id", "name", "email")  # Removed 'role'

    @staticmethod
    def resolve_avatarUrl(obj: User) -> str | None:
        return obj.avatar_url

    @staticmethod
    def resolve_createdAt(obj: User) -> datetime:
        return obj.created_at

    @staticmethod
    def resolve_isCreator(obj: User) -> bool:
        return obj.role in (User.Role.ORGANIZER, User.Role.ADMIN)

    @staticmethod
    def resolve_role(obj: User) -> str:
        return {
            User.Role.USER: "user",
            User.Role.ORGANIZER: "creator",
            User.Role.ADMIN: "admin",
        }.get(obj.role, "user")


class TokenPairSchema(Schema):
    access: str
    refresh: str


class AuthResponseSchema(Schema):
    """
    Unified response wrapper for Login & Register endpoints.
    Payload: { user: UserSchema, tokens: { access, refresh } }
    """

    user: UserSchema
    tokens: TokenPairSchema


# -------------------------------------------------------------------
# Input Schemas (Payloads)
# -------------------------------------------------------------------


class RegisterSchema(Schema):
    name: str
    email: EmailStr
    password: str
    organization: str | None = None


class LoginSchema(Schema):
    email: EmailStr
    password: str


class LogoutSchema(Schema):
    refresh: str


class MeUpdateSchema(Schema):
    """
    PATCH /auth/me/ input payload. All fields optional for partial updates.
    """

    name: str | None = None
    avatarUrl: str | None = None


class ResetPasswordSchema(Schema):
    email: EmailStr
