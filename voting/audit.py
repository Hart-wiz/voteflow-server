"""Audit log creation helpers used across application layers."""

from .models import AuditLog
from .utils import extract_device_fingerprint, hash_ip_address_safe


def create_audit_log(
    *,
    action_type,
    user=None,
    resource_type="",
    resource_id="",
    request=None,
    metadata=None,
    ip_address=None,
    device_fingerprint=None,
):
    ip = ip_address or (request.META.get("REMOTE_ADDR") if request else None)
    device = device_fingerprint
    if device is None and request is not None:
        device = extract_device_fingerprint(request)
    return AuditLog.objects.create(
        user=user if user and user.is_authenticated else None,
        action_type=action_type,
        resource_type=(resource_type or "Unknown")[:100],
        resource_id=str(resource_id or "unknown")[:255],
        ip_hash=hash_ip_address_safe(ip),
        device_fingerprint=(device or "")[:512],
        metadata=metadata or {},
    )
