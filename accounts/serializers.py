"""
Serializers for the accounts app.

Handles user registration, login, and profile serialization.
All field names use camelCase to match the frontend's TypeScript interfaces.

Frontend expects UserObj:  { id, name, email, avatarUrl, role, createdAt }
Login/Register response:   { user: UserObj, tokens: { access, refresh } }
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Read-only representation of a User.
    Used in auth responses and GET /auth/me/.
    """
    avatarUrl = serializers.URLField(source="avatar_url", required=False, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = User
        fields = ["id", "name", "email", "avatarUrl", "role", "createdAt"]
        read_only_fields = ["id", "createdAt"]


class RegisterSerializer(serializers.Serializer):
    """
    POST /auth/register/
    Payload:  { name, email, password }
    Response: { user: UserObj, tokens: { access, refresh } }
    """
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            name=validated_data["name"],
            password=validated_data["password"],
        )
        return user

    def to_representation(self, instance):
        tokens = RefreshToken.for_user(instance)
        return {
            "user": UserSerializer(instance).data,
            "tokens": {
                "access": str(tokens.access_token),
                "refresh": str(tokens),
            },
        }


class LoginSerializer(serializers.Serializer):
    """
    POST /auth/login/
    Payload:  { email, password }
    Response: { user: UserObj, tokens: { access, refresh } }
    """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower()
        password = attrs["password"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active:
            raise serializers.ValidationError("This account has been deactivated.")

        attrs["user"] = user
        return attrs

    def create(self, validated_data):
        # Not creating anything — just returning the user with tokens
        return validated_data["user"]

    def to_representation(self, instance):
        tokens = RefreshToken.for_user(instance)
        return {
            "user": UserSerializer(instance).data,
            "tokens": {
                "access": str(tokens.access_token),
                "refresh": str(tokens),
            },
        }


class MeUpdateSerializer(serializers.ModelSerializer):
    """
    PATCH /auth/me/
    Allows updating name, avatarUrl, and role.
    """
    avatarUrl = serializers.URLField(
        source="avatar_url", required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = ["name", "avatarUrl", "role"]

    def to_representation(self, instance):
        return UserSerializer(instance).data
