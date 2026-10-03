"""
Custom permissions and authorization helpers for VoteFlow (Django Ninja).
"""


# ---------------------------------------------------------------------------
# Role-based Authorization Helpers
# ---------------------------------------------------------------------------


def is_organizer_or_admin(user) -> bool:
    """Check if the user has 'ORGANIZER' (creator) or 'ADMIN' privileges."""
    if not user or not user.is_authenticated:
        return False
    # Matching your User.Role TextChoices: ORGANIZER / ADMIN
    return user.role in ("ORGANIZER", "ADMIN") or user.is_superuser


is_creator = is_organizer_or_admin


def is_poll_owner(user, poll) -> bool:
    """
    Object-level check: only the poll's creator can modify it.
    Admins bypass this check.
    """
    if not user or not user.is_authenticated:
        return False
    if user.role == "ADMIN" or user.is_superuser:
        return True
    return poll.creator_id == user.id
