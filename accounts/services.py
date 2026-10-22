"""Business services for organizer access requests."""

from django.db import transaction
from django.utils import timezone

from accounts.models import OrganizerProfile, User
from notifications.email import send_transactional_email
from notifications.models import Notification
from voting.models import AuditLog


def request_organizer_privileges(user, business_name="", bio=""):
    """Create or update the authenticated user's pending organizer request."""
    if user.role in (User.Role.ORGANIZER, User.Role.ADMIN):
        return None, False
    profile, created = OrganizerProfile.objects.get_or_create(
        user=user,
        defaults={"business_name": business_name.strip(), "bio": bio.strip()},
    )
    if not created and not profile.is_approved:
        profile.business_name = business_name.strip() or profile.business_name
        profile.bio = bio.strip() or profile.bio
        profile.save(update_fields=["business_name", "bio", "updated_at"])
    return profile, created


@transaction.atomic
def approve_organizer_request(admin, profile_id):
    """Approve a pending request, promote its owner, and record the change."""
    if admin.role != User.Role.ADMIN:
        raise PermissionError("Administrator access is required.")
    profile = OrganizerProfile.objects.select_for_update().select_related("user").get(id=profile_id)
    if profile.is_approved:
        return profile, False

    profile.is_approved = True
    profile.approved_at = timezone.now()
    profile.approved_by = admin
    profile.save(update_fields=["is_approved", "approved_at", "approved_by", "updated_at"])
    profile.user.role = User.Role.ORGANIZER
    profile.user.save(update_fields=["role", "updated_at"])

    AuditLog.objects.create(
        user=admin,
        action_type=AuditLog.ActionType.ROLE_CHANGE,
        resource_type="OrganizerProfile",
        resource_id=str(profile.id),
        metadata={"user_id": str(profile.user_id), "new_role": User.Role.ORGANIZER},
    )
    Notification.objects.create(
        receiver=profile.user,
        title="Organizer access approved",
        description="Your organizer request was approved. You can now create and manage polls.",
        email=profile.user.email,
    )
    transaction.on_commit(lambda: _send_approval_email(profile.user.email))
    return profile, True


@transaction.atomic
def reject_organizer_request(admin, profile_id):
    """Reject a pending request and retain an audit trail of the decision."""
    if admin.role != User.Role.ADMIN:
        raise PermissionError("Administrator access is required.")
    profile = OrganizerProfile.objects.select_for_update().select_related("user").filter(
        id=profile_id,
        is_approved=False,
    ).first()
    if not profile:
        return False

    user = profile.user
    Notification.objects.create(
        receiver=user,
        title="Organizer request declined",
        description="Your organizer request was not approved. Contact support if you need help.",
        email=user.email,
    )
    AuditLog.objects.create(
        user=admin,
        action_type=AuditLog.ActionType.ROLE_CHANGE,
        resource_type="OrganizerProfile",
        resource_id=str(profile.id),
        metadata={"user_id": str(user.id), "decision": "rejected"},
    )
    profile.delete()
    return True


def _send_approval_email(email):
    try:
        send_transactional_email(
            to=email,
            subject="Your VoteFlow organizer request was approved",
            text="Your organizer request has been approved. Sign in to create and manage polls.",
            html="<p>Your organizer request has been approved. Sign in to create and manage polls.</p>",
        )
    except Exception:
        # Approval is committed even if the email provider is temporarily unavailable.
        import logging

        logging.getLogger(__name__).exception("Could not send organizer approval email to %s", email)
