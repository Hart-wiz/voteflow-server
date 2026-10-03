# accounts/utils.py
import random

from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import UserOTP  # Ensure you still create the database model for OTP


def send_verification_email_and_otp(request, user):
    # 1. Encode user primary key safely to base64
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # 2. Generate a secure, single-use activation hash token
    token = default_token_generator.make_token(user)

    # 3. Create the destination interface target URL string (FIXED URL)
    current_site = get_current_site(
        request
    ).domain  # Resolves dynamically to 127.0.0.1:8000 or production domain
    verification_url = f"http://{current_site}/api/activate/{uid}/{token}/"

    # 4. Generate and save the 6-Digit OTP code to database
    otp_profile, _created = UserOTP.objects.get_or_create(user=user)
    otp_profile.otp_code = f"{random.randint(100000, 999999)}"
    otp_profile.created_at = timezone.now()
    otp_profile.save()

    # 5. Construct unified message body
    subject = "Verify your VoteFlow Account"
    message = (
        f"Hi {user.username},\n\n"
        f"Thank you for registering with VoteFlow! Choose one method below to verify your account:\n\n"
        f"Option 1: Click this link to activate your account:\n{verification_url}\n\n"
        f"Option 2: Enter this 6-digit One-Time Passcode (OTP):\n{otp_profile.otp_code}\n"
        f"(The OTP expires in 10 minutes.)"
    )

    # 6. Dispatch email via core infrastructure
    send_mail(
        subject=subject,
        message=message,
        from_email=None,  # Automatically falls back to settings.DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )
