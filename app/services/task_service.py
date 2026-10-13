from datetime import datetime
from typing import Any

from app.models import DocumentNotFoundError
from app.models.common import now_utc
from app.models.task import Task
from app.services.firestore import FirestoreService
from app.services.subject_service import SubjectService


class TaskService:
    _COLLECTION = "tasks"
    _UPDATABLE_FIELDS = {
        "title",
        "description",
        "subject_id",
        "deadline",
        "priority",
        "category",
        "status",
        "tags",
        "alarm_enabled",
    }

    def __init__(
        self, firestore: FirestoreService, subjects: SubjectService | None = None
    ) -> None:
        self._firestore = firestore
        self._subjects = subjects or SubjectService(firestore)

    async def create_task(
        self,
        title: str,
        deadline: datetime | None,
        description: str = "",
        subject_id: str | None = None,
        priority: str = "medium",
        category: str = "general",
        status: str = "pending",
        tags: list[str] | None = None,
        task_id: str | None = None,
        alarm_enabled: bool = True,
    ) -> Task:
        task = Task(
            id=task_id or "pending-id",
            title=title,
            deadline=deadline,
            description=description,
            subject_id=subject_id,
            priority=priority,
            category=category,
            status=status,
            tags=[] if tags is None else tags,
            alarm_enabled=alarm_enabled,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        if subject_id is not None:
            await self._require_subject(subject_id)
        created_id = await self._firestore.create_document(
            self._COLLECTION,
            task.to_firestore(),
            document_id=task_id,
        )
        return Task(
            id=created_id,
            title=task.title,
            deadline=task.deadline,
            description=task.description,
            subject_id=task.subject_id,
            priority=task.priority,
            category=task.category,
            status=task.status,
            tags=task.tags,
            alarm_enabled=task.alarm_enabled,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    async def get_task(self, task_id: str) -> Task | None:
        document = await self._firestore.read_document(self._COLLECTION, task_id)
        if document is None:
            return None
        return Task.from_firestore(document.document_id, document.data)

    async def get_tasks(self) -> list[Task]:
        documents = await self._firestore.list_documents(self._COLLECTION)
        return [
            Task.from_firestore(document.document_id, document.data)
            for document in documents
        ]

    async def update_task(self, task_id: str, changes: dict[str, Any]) -> Task:
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Provide at least one task field to update.")
        invalid_fields = changes.keys() - self._UPDATABLE_FIELDS
        if invalid_fields:
            raise ValueError(
                "Unsupported task field(s): " + ", ".join(sorted(invalid_fields))
            )
        existing = await self.get_task(task_id)
        if existing is None:
            raise DocumentNotFoundError(f"Task '{task_id}' does not exist.")
        values = existing.to_firestore()
        values.update(changes)
        values["updated_at"] = now_utc()
        updated = Task.from_firestore(existing.id, values)
        if updated.subject_id is not None and updated.subject_id != existing.subject_id:
            await self._require_subject(updated.subject_id)
        updated_data = updated.to_firestore()
        patch = {
            field: updated_data[field]
            for field in changes
        }
        patch["updated_at"] = updated_data["updated_at"]
        await self._firestore.update_document(self._COLLECTION, task_id, patch)
        return updated

    async def delete_task(self, task_id: str) -> None:
        existing = await self.get_task(task_id)
        if existing is None:
            raise DocumentNotFoundError(f"Task '{task_id}' does not exist.")
        await self._firestore.delete_document(self._COLLECTION, task_id)

    async def _require_subject(self, subject_id: str) -> None:
        if await self._subjects.get_subject(subject_id) is None:
            raise DocumentNotFoundError(
                f"Subject '{subject_id}' does not exist for the current user."
            )
