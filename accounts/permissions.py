"""Role and object permissions for Django Ninja endpoints."""

from functools import wraps

from config.errors import AuthenticationError, AuthorizationError, ResourceNotFoundError


def is_organizer_or_admin(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.role in ("ORGANIZER", "ADMIN") or user.is_superuser


is_creator = is_organizer_or_admin


def is_poll_owner(user, poll) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.role == "ADMIN" or user.is_superuser:
        return True
    return user.role == "ORGANIZER" and poll.creator_id == user.id


def require_role(*allowed_roles):
    """Restrict a Django Ninja endpoint to authenticated users with a role."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = getattr(request, "user", None)
            if not user or not user.is_authenticated:
                raise AuthenticationError()
            if user.role not in allowed_roles and not user.is_superuser:
                raise AuthorizationError()
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def require_poll_ownership(view):
    """Restrict a poll mutation to its organizer or an administrator."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise AuthenticationError()
        slug = kwargs.get("slug")
        if slug is None and args:
            slug = args[0]
        if not slug:
            raise ResourceNotFoundError("A poll slug is required.")
        from polls.models import Poll

        try:
            poll = Poll.objects.get(slug=slug)
        except Poll.DoesNotExist as exc:
            raise ResourceNotFoundError("Poll not found.") from exc
        if not is_poll_owner(user, poll):
            raise AuthorizationError("You do not have permission to manage this poll.")
        request.poll = poll
        return view(request, *args, **kwargs)

    return wrapped


def require_contest_ownership(view):
    """Restrict contest mutations to the organizer or an administrator."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise AuthenticationError()
        slug = kwargs.get("slug")
        if slug is None and args:
            slug = args[0]
        if not slug:
            raise ResourceNotFoundError("A contest slug is required.")
        from polls.models import Contest

        try:
            contest = Contest.objects.get(slug=slug)
        except Contest.DoesNotExist as exc:
            raise ResourceNotFoundError("Contest not found.") from exc
        if not (user.is_superuser or user.role == "ADMIN" or contest.organizer_id == user.id):
            raise AuthorizationError("You do not have permission to manage this contest.")
        request.contest = contest
        return view(request, *args, **kwargs)

    return wrapped
