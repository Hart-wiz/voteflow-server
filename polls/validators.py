import zoneinfo

from django.core.exceptions import ValidationError


def validate_iana_timezone(value: str) -> None:
    """
    Validates that a string is a valid IANA timezone identifier.
    Top-level function required for Django migration serialization.
    """
    if value not in zoneinfo.available_timezones():
        raise ValidationError(
            f"{value} is not a valid IANA timezone identifier.", code="invalid_timezone"
        )
