"""
Custom permissions for VoteFlow.

IsCreator       — user.role is 'creator' or 'admin'
IsCreatorOrAdmin — alias (same logic, explicit name)
IsPollOwner     — object-level: poll.creator == request.user
"""

from rest_framework.permissions import BasePermission


class IsCreator(BasePermission):
    """Allow access only to users with role 'creator' or 'admin'."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in ("creator", "admin")
        )


class IsCreatorOrAdmin(BasePermission):
    """Same as IsCreator — explicit naming for clarity in ViewSets."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role in ("creator", "admin")
        )


class IsPollOwner(BasePermission):
    """
    Object-level permission: only the poll's creator can modify it.
    Admins bypass this check.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True
        return obj.creator == request.user