from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models import ModelValidationError
from app.models.common import now_utc, parse_datetime, require_text


@dataclass(frozen=True)
class Subject:
    id: str
    title: str
    color: str
    description: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_text(self.id, "id")
        require_text(self.title, "title")
        require_text(self.color, "color")
        require_text(self.description, "description", allow_empty=True)
        object.__setattr__(self, "created_at", parse_datetime(self.created_at, "created_at"))

    def to_firestore(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "color": self.color,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_firestore(cls, document_id: str, data: dict[str, Any]) -> "Subject":
        if not isinstance(data, dict):
            raise ModelValidationError("Subject data must be a mapping.")
        try:
            return cls(
                id=document_id,
                title=data["title"],
                color=data.get("color", "#2196F3"),
                description=data.get("description", ""),
                created_at=data["created_at"],
            )
        except KeyError as error:
            raise ModelValidationError(
                f"Subject data is missing required field: {error.args[0]}."
            ) from error
