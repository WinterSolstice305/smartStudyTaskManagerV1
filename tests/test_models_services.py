import asyncio
import unittest
from datetime import datetime, timezone
from typing import Any

from app.models import DocumentNotFoundError, ModelValidationError
from app.models.subject import Subject
from app.models.task import Task
from app.services.firestore import FirestoreDocument
from app.services.subject_service import SubjectInUseError, SubjectService
from app.services.task_service import TaskService


class FakeFirestore:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, dict[str, Any]]] = {}
        self.next_id = 0

    async def create_document(
        self,
        collection: str,
        data: dict[str, Any],
        document_id: str | None = None,
    ) -> str:
        self.next_id += 1
        document_id = document_id or f"generated-{self.next_id}"
        self.collections.setdefault(collection, {})[document_id] = dict(data)
        return document_id

    async def read_document(
        self, collection: str, document_id: str
    ) -> FirestoreDocument | None:
        data = self.collections.get(collection, {}).get(document_id)
        return FirestoreDocument(document_id, dict(data)) if data is not None else None

    async def list_documents(self, collection: str) -> list[FirestoreDocument]:
        return [
            FirestoreDocument(document_id, dict(data))
            for document_id, data in self.collections.get(collection, {}).items()
        ]

    async def update_document(
        self, collection: str, document_id: str, data: dict[str, Any]
    ) -> None:
        self.collections[collection][document_id].update(data)

    async def delete_document(self, collection: str, document_id: str) -> None:
        del self.collections[collection][document_id]


class ModelTests(unittest.TestCase):
    def test_subject_requires_title_and_timezone_aware_timestamp(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "title"):
            Subject("subject-1", " ", "#ffffff", "", datetime.now(timezone.utc))
        with self.assertRaisesRegex(ModelValidationError, "timezone"):
            Subject("subject-1", "Math", "#ffffff", "", datetime(2026, 1, 1))

    def test_task_rejects_invalid_deadline_and_tags(self) -> None:
        with self.assertRaisesRegex(ModelValidationError, "timezone"):
            Task("task-1", "Study", datetime(2026, 1, 1))
        with self.assertRaisesRegex(ModelValidationError, "list of strings"):
            Task(
                "task-1",
                "Study",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                tags=["valid", 3],  # type: ignore[list-item]
            )

    def test_legacy_task_alarm_defaults_off_and_round_trips(self) -> None:
        legacy_data = {
            "title": "Study",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        task = Task.from_firestore("task-1", legacy_data)
        self.assertFalse(task.alarm_enabled)
        self.assertFalse(task.to_firestore()["alarm_enabled"])

        opted_in = Task(
            "task-2",
            "Study",
            None,
            alarm_enabled=True,
        )
        self.assertTrue(
            Task.from_firestore("task-2", opted_in.to_firestore()).alarm_enabled
        )

        with self.assertRaisesRegex(ModelValidationError, "alarm_enabled"):
            Task("task-3", "Study", None, alarm_enabled="yes")  # type: ignore[arg-type]


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.firestore = FakeFirestore()
        self.subjects = SubjectService(self.firestore)  # type: ignore[arg-type]
        self.tasks = TaskService(self.firestore, self.subjects)  # type: ignore[arg-type]
        self.deadline = datetime(2026, 12, 1, 9, tzinfo=timezone.utc)

    def test_subject_crud_and_missing_document(self) -> None:
        async def exercise() -> None:
            subject = await self.subjects.create_subject(
                "Mathematics", description="Calculus", subject_id="math"
            )
            self.assertEqual(subject.id, "math")
            self.assertEqual((await self.subjects.get_subject("math")).title, "Mathematics")
            self.assertEqual([item.id for item in await self.subjects.get_subjects()], ["math"])
            updated = await self.subjects.update_subject(
                "math", {"title": "Advanced Mathematics"}
            )
            self.assertEqual(updated.title, "Advanced Mathematics")
            self.assertEqual(updated.description, "Calculus")
            await self.subjects.delete_subject("math")
            self.assertIsNone(await self.subjects.get_subject("math"))
            with self.assertRaises(DocumentNotFoundError):
                await self.subjects.delete_subject("math")
            with self.assertRaises(ModelValidationError):
                await self.subjects.create_subject(" ")

        asyncio.run(exercise())

    def test_task_subject_assignment_and_crud(self) -> None:
        async def exercise() -> None:
            await self.subjects.create_subject("Mathematics", subject_id="math")
            task = await self.tasks.create_task(
                "Finish problem set",
                self.deadline,
                subject_id="math",
                tags=["homework"],
                task_id="problem-set",
            )
            self.assertEqual(task.subject_id, "math")
            self.assertTrue(task.alarm_enabled)
            retrieved = await self.tasks.get_task("problem-set")
            self.assertIsNotNone(retrieved)
            if retrieved is None:
                raise AssertionError("Created task should be available for retrieval.")
            self.assertEqual(retrieved.title, "Finish problem set")
            self.assertTrue(retrieved.alarm_enabled)
            self.assertEqual(
                [item.id for item in await self.tasks.get_tasks()], ["problem-set"]
            )

            new_deadline = datetime(2026, 12, 5, 15, tzinfo=timezone.utc)
            updated = await self.tasks.update_task(
                "problem-set",
                {
                    "status": "completed",
                    "priority": "high",
                    "category": "exam",
                    "deadline": new_deadline,
                    "tags": ["exam", "review"],
                    "alarm_enabled": False,
                },
            )
            self.assertEqual(updated.status, "completed")
            self.assertEqual(updated.priority, "high")
            self.assertEqual(updated.category, "exam")
            self.assertEqual(updated.deadline, new_deadline)
            self.assertEqual(updated.tags, ["exam", "review"])
            self.assertFalse(updated.alarm_enabled)
            persisted = await self.tasks.get_task("problem-set")
            self.assertIsNotNone(persisted)
            if persisted is None:
                raise AssertionError("Updated task should be available for retrieval.")
            self.assertEqual(persisted.status, "completed")
            self.assertFalse(persisted.alarm_enabled)
            await self.tasks.delete_task("problem-set")
            self.assertIsNone(await self.tasks.get_task("problem-set"))
            with self.assertRaises(DocumentNotFoundError):
                await self.tasks.update_task("missing", {"status": "pending"})
            with self.assertRaises(DocumentNotFoundError):
                await self.tasks.create_task(
                    "Orphan task", self.deadline, subject_id="not-owned"
                )

        asyncio.run(exercise())

    def test_subject_cannot_be_deleted_while_tasks_reference_it(self) -> None:
        async def exercise() -> None:
            await self.subjects.create_subject("Mathematics", subject_id="math")
            await self.tasks.create_task(
                "Finish problem set", self.deadline, subject_id="math"
            )
            with self.assertRaises(SubjectInUseError):
                await self.subjects.delete_subject("math")

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
