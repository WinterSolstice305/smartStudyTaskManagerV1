import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models.task import Task
from app.services.notifications import (
    NotificationPreferences,
    NotificationScheduler,
    _NotificationStateStore,
)


class FakeNotificationAdapter:
    def __init__(self) -> None:
        self.pending: dict[int, dict[str, object]] = {}
        self.scheduled: list[dict[str, object]] = []
        self.cancelled: list[int] = []
        self.fail_schedule = False
        self.fail_cancel = False

    async def get_pending_notifications(self) -> list[dict[str, str]]:
        return [{"id": str(notification_id)} for notification_id in self.pending]

    async def schedule_notification(self, **notification: object) -> None:
        if self.fail_schedule:
            raise RuntimeError("Scheduling unavailable")
        self.scheduled.append(notification)
        notification_id = notification.get("notification_id")
        if not isinstance(notification_id, int):
            raise AssertionError("Scheduled notifications need an integer ID.")
        self.pending[notification_id] = notification

    async def cancel(self, notification_id: int) -> None:
        if self.fail_cancel:
            raise RuntimeError("Cancellation unavailable")
        self.cancelled.append(notification_id)
        self.pending.pop(notification_id, None)


class NotificationSchedulerTests(unittest.TestCase):
    def test_deadline_alarm_is_opt_in_and_reconciliation_is_idempotent(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as directory:
                adapter = FakeNotificationAdapter()
                scheduler = NotificationScheduler(
                    object(),
                    state_store=_NotificationStateStore(
                        Path(directory) / "notifications.json"
                    ),
                )
                scheduler._adapter = adapter
                deadline = datetime.now(timezone.utc) + timedelta(hours=4)
                enabled_task = Task(
                    "enabled",
                    "Enabled task",
                    deadline,
                    alarm_enabled=True,
                )
                disabled_task = Task(
                    "disabled",
                    "Disabled task",
                    deadline,
                    alarm_enabled=False,
                )
                past_task = Task(
                    "past",
                    "Past task",
                    datetime.now(timezone.utc) - timedelta(hours=1),
                    alarm_enabled=True,
                )
                completed_task = Task(
                    "completed",
                    "Completed task",
                    deadline,
                    status="completed",
                    alarm_enabled=True,
                )
                preferences = NotificationPreferences(
                    enabled=True,
                    reminder_24_hours=False,
                    reminder_1_hour=False,
                    overdue_alert=True,
                )
                tasks = [enabled_task, disabled_task, past_task, completed_task]

                with patch.object(
                    scheduler,
                    "permission_granted",
                    new=AsyncMock(return_value=True),
                ):
                    await scheduler.reconcile("user", tasks, [], preferences)
                    self.assertEqual(len(adapter.scheduled), 1)
                    scheduled = adapter.scheduled[0]
                    notification_id = NotificationScheduler.notification_id(
                        "enabled", "deadline"
                    )
                    self.assertEqual(
                        scheduled["notification_id"], notification_id
                    )
                    self.assertEqual(scheduled["scheduled_time"], deadline)
                    self.assertEqual(scheduled["body"], "Deadline reached")

                    await scheduler.reconcile("user", tasks, [], preferences)
                    self.assertEqual(len(adapter.scheduled), 1)

                    updated_deadline = deadline + timedelta(hours=1)
                    updated_task = Task(
                        "enabled",
                        "Enabled task",
                        updated_deadline,
                        alarm_enabled=True,
                    )
                    await scheduler.reconcile(
                        "user", [updated_task], [], preferences
                    )
                    self.assertEqual(len(adapter.scheduled), 2)
                    self.assertEqual(
                        adapter.scheduled[-1]["notification_id"], notification_id
                    )
                    self.assertEqual(
                        adapter.scheduled[-1]["scheduled_time"], updated_deadline
                    )
                    self.assertEqual(adapter.cancelled, [notification_id])

                    disabled_after_edit = Task(
                        "enabled",
                        "Enabled task",
                        updated_deadline,
                        alarm_enabled=False,
                    )
                    await scheduler.reconcile(
                        "user", [disabled_after_edit], [], preferences
                    )

                self.assertEqual(
                    adapter.cancelled,
                    [notification_id, notification_id],
                )

        asyncio.run(exercise())

    def test_schedule_failure_does_not_persist_a_scheduled_event(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = _NotificationStateStore(
                    Path(directory) / "notifications.json"
                )
                scheduler = NotificationScheduler(object(), state_store=store)
                adapter = FakeNotificationAdapter()
                adapter.fail_schedule = True
                scheduler._adapter = adapter
                deadline = datetime.now(timezone.utc) + timedelta(hours=2)
                task = Task(
                    "task",
                    "Task",
                    deadline,
                    alarm_enabled=True,
                )
                preferences = NotificationPreferences(
                    enabled=True,
                    reminder_24_hours=False,
                    reminder_1_hour=False,
                    overdue_alert=True,
                )
                with patch.object(
                    scheduler,
                    "permission_granted",
                    new=AsyncMock(return_value=True),
                ):
                    with self.assertLogs("app.services.notifications", level="WARNING"):
                        await scheduler.reconcile("user", [task], [], preferences)

                self.assertEqual(store.load("user").get("events"), {})

        asyncio.run(exercise())

    def test_failed_cancellation_is_reported_and_retried(self) -> None:
        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as directory:
                store = _NotificationStateStore(
                    Path(directory) / "notifications.json"
                )
                scheduler = NotificationScheduler(object(), state_store=store)
                adapter = FakeNotificationAdapter()
                scheduler._adapter = adapter
                deadline = datetime.now(timezone.utc) + timedelta(hours=2)
                task = Task(
                    "task",
                    "Task",
                    deadline,
                    alarm_enabled=True,
                )
                updated_deadline = deadline + timedelta(hours=1)
                updated_task = Task(
                    "task",
                    "Task",
                    updated_deadline,
                    alarm_enabled=True,
                )
                preferences = NotificationPreferences(
                    enabled=True,
                    reminder_24_hours=False,
                    reminder_1_hour=False,
                    overdue_alert=True,
                )
                with patch.object(
                    scheduler,
                    "permission_granted",
                    new=AsyncMock(return_value=True),
                ):
                    await scheduler.reconcile("user", [task], [], preferences)
                    adapter.fail_cancel = True
                    with self.assertLogs(
                        "app.services.notifications", level="WARNING"
                    ):
                        await scheduler.reconcile(
                            "user", [updated_task], [], preferences
                        )
                    self.assertEqual(len(adapter.scheduled), 1)
                    self.assertIn(
                        "task:deadline", store.load("user").get("events", {})
                    )

                    adapter.fail_cancel = False
                    await scheduler.reconcile(
                        "user", [updated_task], [], preferences
                    )
                    self.assertEqual(len(adapter.scheduled), 2)
                    self.assertEqual(
                        adapter.scheduled[-1]["scheduled_time"], updated_deadline
                    )
                    await scheduler.reconcile("user", [], [], preferences)

                self.assertEqual(store.load("user").get("events"), {})

        asyncio.run(exercise())
