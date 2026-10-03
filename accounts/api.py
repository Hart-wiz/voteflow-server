"""
Auth views for VoteFlow.

Endpoints:
    POST /api/v1/auth/register/     → RegisterView
    POST /api/v1/auth/login/        → LoginView
    POST /api/v1/auth/logout/       → LogoutView
    POST /api/v1/auth/token/refresh/ → (SimpleJWT built-in)
    GET  /api/v1/auth/me/           → MeView  (returns current user)
    PATCH /api/v1/auth/me/          → MeView  (updates current user)
"""

import random

from django.core.mail import send_mail
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from .models import User, UserOTP
from .schemas import (
    AuthResponseSchema,
    LoginSchema,
    LogoutSchema,
    RegisterSchema,
    ResetPasswordSchema,
    TokenPairSchema,
    UserSchema,
)

router = Router(tags=["Auth"])


@router.post("/register", response={201: AuthResponseSchema})
def register(request, payload: RegisterSchema):
    """
    Create a new user account.
    Returns the user object and JWT tokens.
    """
    if User.objects.filter(email=payload.email).exists():
        raise HttpError(400, "User with this email already exists.")

    # Create user
    user = User.objects.create_user(
        email=payload.email, name=payload.name, password=payload.password
    )

    # Generate JWT pair
    refresh = RefreshToken.for_user(user)  # type: ignore

    return 201, {
        "user": user,
        "tokens": {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        },
    }
    # def post(self, request):
    #     serializer = self.get_serializer(data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #     serializer.save()
    #     return Response(serializer.data, status=status.HTTP_201_CREATED)


@router.post("/login", response={200: AuthResponseSchema})
def login(request, payload: LoginSchema) -> AuthResponseSchema:
    user = User.objects.filter(email=payload.email).first()

    if not user or not user.check_password(payload.password):
        raise HttpError(400, "Invalid email or password")

    if not user.is_active:
        raise HttpError(400, "This account has been deactivated")

    refresh = RefreshToken.for_user(user)  # type: ignore
    return AuthResponseSchema(
        user=UserSchema.from_orm(user),
        tokens=TokenPairSchema(
            access=str(refresh.access_token),
            refresh=str(refresh),
        ),
    )


def logout(request, paylod: LogoutSchema):
    refresh_token = paylod.refresh
    if not refresh_token:
        raise HttpError(400, "Refresh token is required")
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        raise HttpError(400, "Token is invalid or blacklisted")
    return 205, {"success": True, "ok": True}


@router.post("/send-reset-code")
def send_reset_code(request, payload: ResetPasswordSchema):
    user = User.objects.filter(email=payload.email).first()

    if not user:
        raise HttpError(400, "User with the email provided does not exist")

    otp_profile, created = UserOTP.objects.get_or_create(user=user)
    otp_profile.otp_code = f"{random.randint(100000, 999999)}"
    if created:
        otp_profile.created_at = timezone.now()
    otp_profile.save()

    subject = "OTP code for password reset"
    message = (
        f"Hi {user.name}, \n\n"
        f"You've requested a token to reset your password, Input the token below to get started"
        f"{otp_profile.otp_code}"
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )

    return 200, {"success": True, "ok": True, "message": "OTP code has been sent"}


def reset_password(request):
    pass


@router.get("/me", response={200: UserSchema}, auth=JWTAuth())
def get_me(request):
    return request.user


# class MeView(GenericAPIView):
#     """
#     GET  → returns the authenticated user's profile.
#     PATCH → partially updates the authenticated user's profile.
#     """

#     permission_classes = [IsAuthenticated]

#     def get_serializer_class(self):
#         if self.request.method == "PATCH":
#             return MeUpdateSerializer
#         return UserSerializer

#     def get(self, request):
#         serializer = UserSerializer(request.user)
#         return Response(serializer.data)

#     def patch(self, request):
#         serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
#         serializer.is_valid(raise_exception=True)
#         serializer.save()
#         return Response(serializer.data)
