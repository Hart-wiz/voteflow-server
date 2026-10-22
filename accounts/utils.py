# accounts/utils.py
import html
import secrets

from django.utils import timezone

from notifications.email import send_transactional_email

from .models import UserOTP


def send_verification_email_and_otp(request, user):
    del request  # Kept in the function signature for existing callers.
    otp_profile, _created = UserOTP.objects.get_or_create(user=user)
    otp_profile.otp_code = f"{secrets.randbelow(900000) + 100000}"
    otp_profile.created_at = timezone.now()
    otp_profile.save()

    name = html.escape(user.name)
    code = otp_profile.otp_code
    send_transactional_email(
        to=user.email,
        subject="Verify your VoteFlow account",
        text=f"Hi {user.name}, your VoteFlow verification code is {code}. It expires in 10 minutes.",
        html=f"<p>Hi {name},</p><p>Your VoteFlow verification code is <strong>{code}</strong>.</p><p>It expires in 10 minutes.</p>",
    )
