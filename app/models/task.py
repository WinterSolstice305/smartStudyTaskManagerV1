from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models import ModelValidationError
from app.models.common import (
    now_utc,
    parse_datetime,
    parse_optional_datetime,
    require_text,
)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    deadline: datetime | None
    description: str = ""
    subject_id: str | None = None
    priority: str = "medium"
    category: str = "general"
    status: str = "pending"
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)

    def __post_init__(self) -> None:
        require_text(self.id, "id")
        require_text(self.title, "title")
        require_text(self.description, "description", allow_empty=True)
        if self.subject_id is not None:
            require_text(self.subject_id, "subject_id")
        require_text(self.priority, "priority")
        require_text(self.category, "category")
        require_text(self.status, "status")
        if not isinstance(self.tags, list) or any(
            not isinstance(tag, str) for tag in self.tags
        ):
            raise ModelValidationError("tags must be a list of strings.")
        object.__setattr__(
            self, "deadline", parse_optional_datetime(self.deadline, "deadline")
        )
        object.__setattr__(
            self, "created_at", parse_datetime(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", parse_datetime(self.updated_at, "updated_at")
        )
        object.__setattr__(self, "tags", list(self.tags))

    def to_firestore(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "subject_id": self.subject_id,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "priority": self.priority,
            "category": self.category,
            "status": self.status,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_firestore(cls, document_id: str, data: dict[str, Any]) -> "Task":
        if not isinstance(data, dict):
            raise ModelValidationError("Task data must be a mapping.")
        try:
            return cls(
                id=document_id,
                title=data["title"],
                deadline=data["deadline"],
                description=data.get("description", ""),
                subject_id=data.get("subject_id"),
                priority=data.get("priority", "medium"),
                category=data.get("category", "general"),
                status=data.get("status", "pending"),
                tags=data.get("tags", []),
                created_at=data["created_at"],
                updated_at=data["updated_at"],
            )
        except KeyError as error:
            raise ModelValidationError(
                f"Task data is missing required field: {error.args[0]}."
            ) from error
