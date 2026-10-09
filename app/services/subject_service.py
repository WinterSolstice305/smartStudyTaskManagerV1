from typing import Any

from app.models import DocumentNotFoundError
from app.models.common import now_utc
from app.models.subject import Subject
from app.services.firestore import FirestoreService


class SubjectInUseError(ValueError):
    """Raised when a subject is still referenced by one or more tasks."""


class SubjectService:
    _COLLECTION = "subjects"
    _UPDATABLE_FIELDS = {"title", "color", "description"}

    def __init__(self, firestore: FirestoreService) -> None:
        self._firestore = firestore

    async def create_subject(
        self,
        title: str,
        color: str = "#2196F3",
        description: str = "",
        subject_id: str | None = None,
    ) -> Subject:
        subject = Subject(
            id=subject_id or "pending-id",
            title=title,
            color=color,
            description=description,
            created_at=now_utc(),
        )
        created_id = await self._firestore.create_document(
            self._COLLECTION,
            subject.to_firestore(),
            document_id=subject_id,
        )
        return Subject(
            id=created_id,
            title=subject.title,
            color=subject.color,
            description=subject.description,
            created_at=subject.created_at,
        )

    async def get_subject(self, subject_id: str) -> Subject | None:
        document = await self._firestore.read_document(self._COLLECTION, subject_id)
        if document is None:
            return None
        return Subject.from_firestore(document.document_id, document.data)

    async def get_subjects(self) -> list[Subject]:
        documents = await self._firestore.list_documents(self._COLLECTION)
        return [
            Subject.from_firestore(document.document_id, document.data)
            for document in documents
        ]

    async def update_subject(
        self, subject_id: str, changes: dict[str, Any]
    ) -> Subject:
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Provide at least one subject field to update.")
        invalid_fields = changes.keys() - self._UPDATABLE_FIELDS
        if invalid_fields:
            raise ValueError(
                "Unsupported subject field(s): " + ", ".join(sorted(invalid_fields))
            )
        existing = await self.get_subject(subject_id)
        if existing is None:
            raise DocumentNotFoundError(f"Subject '{subject_id}' does not exist.")
        updated = Subject(
            id=existing.id,
            title=changes.get("title", existing.title),
            color=changes.get("color", existing.color),
            description=changes.get("description", existing.description),
            created_at=existing.created_at,
        )
        updated_data = updated.to_firestore()
        await self._firestore.update_document(
            self._COLLECTION,
            subject_id,
            {field: updated_data[field] for field in changes},
        )
        return updated

    async def delete_subject(self, subject_id: str) -> None:
        existing = await self.get_subject(subject_id)
        if existing is None:
            raise DocumentNotFoundError(f"Subject '{subject_id}' does not exist.")
        tasks = await self._firestore.list_documents("tasks")
        if any(task.data.get("subject_id") == subject_id for task in tasks):
            raise SubjectInUseError(
                f"Subject '{subject_id}' is assigned to one or more tasks."
            )
        await self._firestore.delete_document(self._COLLECTION, subject_id)
