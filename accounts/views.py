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

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .serializers import RegisterSerializer, LoginSerializer, UserSerializer, MeUpdateSerializer


class RegisterView(GenericAPIView):
    """
    Create a new user account.
    Returns the user object and JWT tokens.
    """
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    """
    Authenticate with email + password.
    Returns the user object and JWT tokens.
    """
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(GenericAPIView):
    """
    Blacklist the provided refresh token.
    Payload: { "refresh": "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Token is invalid or already blacklisted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(GenericAPIView):
    """
    GET  → returns the authenticated user's profile.
    PATCH → partially updates the authenticated user's profile.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return MeUpdateSerializer
        return UserSerializer

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
