from datetime import datetime, timezone
from typing import Any

from app.models import ModelValidationError


def require_text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ModelValidationError(f"{field} must be a non-empty string.")
    return value


def parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ModelValidationError(
                f"{field} must be an ISO-8601 date and time."
            ) from error
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ModelValidationError(f"{field} must include a timezone.")
    return value.astimezone(timezone.utc)


def parse_optional_datetime(value: Any, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    return parse_datetime(value, field)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
