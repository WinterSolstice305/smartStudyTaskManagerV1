"""Local Android deadline notification scheduling.

The task database remains authoritative. This module only stores notification
preferences and the local schedule bookkeeping needed to reconcile Android's
scheduled notification requests after task/cache changes or app restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from app.models.subject import Subject
from app.models.task import Task
from app.services.storage import ensure_storage_root, storage_path


logger = logging.getLogger(__name__)
_CHANNEL_ID = "task_deadlines"
_STATE_VERSION = 1


@dataclass(frozen=True)
class NotificationPreferences:
    enabled: bool = False
    reminder_24_hours: bool = True
    reminder_1_hour: bool = True
    overdue_alert: bool = True


@dataclass(frozen=True)
class _NotificationPlan:
    notification_id: int
    task_id: str
    kind: str
    deadline: str
    scheduled_at: datetime
    title: str
    body: str
    payload: str

    @property
    def key(self) -> str:
        return f"{self.task_id}:{self.kind}"


class _NotificationStateStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or storage_path("notification-state.json")

    def load(self, uid: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        user_state = payload.get(uid)
        return dict(user_state) if isinstance(user_state, dict) else {}

    def save(self, uid: str, state: dict[str, Any]) -> None:
        try:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload[uid] = state
            ensure_storage_root()
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self._path)
        except OSError as error:
            logger.warning("Could not persist notification state: %s", error)


class NotificationScheduler:
    """Reconcile task deadline notifications with the Android scheduler."""

    def __init__(
        self,
        page: Any,
        *,
        state_store: _NotificationStateStore | None = None,
        on_tap: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        self._page = page
        self._state_store = state_store or _NotificationStateStore()
        self._on_tap = on_tap
        self._adapter: Any | None = None
        self._adapter_error = ""
        self._initialize_adapter()

    def _initialize_adapter(self) -> None:
        if sys.platform != "android":
            return
        try:
            from flet_android_notifications import FletAndroidNotifications

            self._adapter = FletAndroidNotifications()
            self._adapter.on_notification_tap = self._handle_tap
            self._page.services.append(self._adapter)
        except (ImportError, AttributeError, RuntimeError) as error:
            self._adapter_error = str(error)
            logger.warning("Android notifications are unavailable: %s", error)

    @property
    def platform_available(self) -> bool:
        return self._adapter is not None

    @property
    def unavailable_reason(self) -> str:
        if self.platform_available:
            return ""
        if sys.platform != "android":
            return "Android notifications are available in Android builds."
        return self._adapter_error or "The Android notification package is unavailable."

    def get_preferences(self, uid: str) -> NotificationPreferences:
        state = self._state_store.load(uid)
        raw = state.get("preferences", {})
        if not isinstance(raw, dict):
            return NotificationPreferences()
        defaults = NotificationPreferences()
        return NotificationPreferences(
            enabled=raw.get("enabled", defaults.enabled) is True,
            reminder_24_hours=raw.get(
                "reminder_24_hours", defaults.reminder_24_hours
            ) is True,
            reminder_1_hour=raw.get("reminder_1_hour", defaults.reminder_1_hour)
            is True,
            overdue_alert=raw.get("overdue_alert", defaults.overdue_alert) is True,
        )

    def save_preferences(self, uid: str, preferences: NotificationPreferences) -> None:
        state = self._state_store.load(uid)
        state["preferences"] = asdict(preferences)
        state.setdefault("events", {})
        self._state_store.save(uid, state)

    async def request_permission(self) -> bool | None:
        if self._adapter is None:
            return None
        try:
            return await self._adapter.request_permissions()
        except Exception as error:
            logger.warning("Could not request notification permission: %s", error)
            return False

    async def permission_granted(self) -> bool | None:
        if self._adapter is None:
            return None
        try:
            return await self._adapter.are_notifications_enabled()
        except Exception as error:
            logger.warning("Could not inspect notification permission: %s", error)
            return False

    async def open_permission_settings(self) -> bool:
        if self._adapter is None:
            return False
        try:
            return await self._adapter.open_app_notification_settings()
        except Exception as error:
            logger.warning("Could not open notification settings: %s", error)
            return False

    async def reconcile(
        self,
        uid: str,
        tasks: Sequence[Task],
        subjects: Sequence[Subject],
        preferences: NotificationPreferences | None = None,
    ) -> None:
        preferences = preferences or self.get_preferences(uid)
        state = self._state_store.load(uid)
        events = state.get("events", {})
        if not isinstance(events, dict):
            events = {}

        pending_ids: set[int] = set()
        if self._adapter is not None:
            try:
                pending = await self._adapter.get_pending_notifications()
                pending_ids = {
                    int(item["id"])
                    for item in pending
                    if isinstance(item, dict) and str(item.get("id", "")).isdigit()
                }
            except Exception as error:
                logger.warning("Could not inspect pending notifications: %s", error)

        if not preferences.enabled or self._adapter is None:
            state["events"] = await self._cancel_events(events)
            self._state_store.save(uid, state)
            return

        permission = await self.permission_granted()
        if permission is not True:
            state["events"] = await self._cancel_events(events)
            self._state_store.save(uid, state)
            return

        now = datetime.now(timezone.utc)
        subject_names = {subject.id: subject.title for subject in subjects}
        plans: dict[str, _NotificationPlan] = {}
        for task in tasks:
            if task.status == "completed" or task.deadline is None:
                continue
            deadline = task.deadline.astimezone(timezone.utc)
            deadline_key = deadline.isoformat()
            subject = subject_names.get(task.subject_id or "")
            label = f" ({subject})" if subject else ""
            base_title = task.title.strip() or "Study task"
            if preferences.reminder_24_hours:
                self._add_future_plan(
                    plans,
                    task,
                    "24h",
                    deadline - timedelta(hours=24),
                    deadline_key,
                    f"{base_title}{label}",
                    "Due tomorrow",
                    now,
                )
            if preferences.reminder_1_hour:
                self._add_future_plan(
                    plans,
                    task,
                    "1h",
                    deadline - timedelta(hours=1),
                    deadline_key,
                    f"{base_title}{label}",
                    "Due in 1 hour",
                    now,
                )
            if preferences.overdue_alert and task.alarm_enabled:
                self._add_future_plan(
                    plans,
                    task,
                    "deadline",
                    deadline,
                    deadline_key,
                    f"{base_title}{label}",
                    "Deadline reached",
                    now,
                )

        for key, old in list(events.items()):
            if not isinstance(old, dict):
                events.pop(key, None)
                continue
            plan = plans.get(key)
            if plan is None or not self._event_matches(old, plan):
                notification_id = self._event_id(old, key)
                if await self._cancel(notification_id):
                    events.pop(key, None)

        for key, plan in plans.items():
            old = events.get(key)
            if isinstance(old, dict):
                if not self._event_matches(old, plan):
                    continue
                if int(old.get("id", 0)) in pending_ids:
                    continue
                events.pop(key, None)
            try:
                await self._adapter.schedule_notification(
                    notification_id=plan.notification_id,
                    title=plan.title,
                    body=plan.body,
                    scheduled_time=plan.scheduled_at,
                    payload=plan.payload,
                    schedule_mode="inexact_allow_while_idle",
                    channel_id=_CHANNEL_ID,
                    channel_name="Task deadlines",
                    category="reminder",
                )
                events[key] = {
                    "id": plan.notification_id,
                    "task_id": plan.task_id,
                    "kind": plan.kind,
                    "deadline": plan.deadline,
                    "scheduled_at": plan.scheduled_at.isoformat(),
                    "status": "scheduled",
                }
            except Exception as error:
                logger.warning(
                    "Could not schedule task notification %s for %s: %s",
                    plan.kind,
                    plan.task_id,
                    error,
                )

        state["events"] = events
        state["version"] = _STATE_VERSION
        self._state_store.save(uid, state)

    @staticmethod
    def _add_future_plan(
        plans: dict[str, _NotificationPlan],
        task: Task,
        kind: str,
        scheduled_at: datetime,
        deadline_key: str,
        title: str,
        body: str,
        now: datetime,
    ) -> None:
        if scheduled_at <= now:
            return
        plan = NotificationScheduler._make_plan(
            task, kind, scheduled_at, deadline_key, title, body
        )
        plans[plan.key] = plan

    @staticmethod
    def _make_plan(
        task: Task,
        kind: str,
        scheduled_at: datetime,
        deadline_key: str,
        title: str,
        body: str,
    ) -> _NotificationPlan:
        notification_id = NotificationScheduler.notification_id(task.id, kind)
        return _NotificationPlan(
            notification_id=notification_id,
            task_id=task.id,
            kind=kind,
            deadline=deadline_key,
            scheduled_at=scheduled_at,
            title=title,
            body=body,
            payload=json.dumps({"task_id": task.id, "kind": kind}),
        )

    @staticmethod
    def notification_id(task_id: str, kind: str) -> int:
        digest = hashlib.sha256(f"smart-study:{task_id}:{kind}".encode()).digest()
        value = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
        return value or 1

    @staticmethod
    def _event_matches(event: dict[str, Any], plan: _NotificationPlan) -> bool:
        return (
            event.get("id") == plan.notification_id
            and event.get("task_id") == plan.task_id
            and event.get("kind") == plan.kind
            and event.get("deadline") == plan.deadline
            and event.get("scheduled_at") == plan.scheduled_at.isoformat()
        )

    @staticmethod
    def _event_id(event: dict[str, Any], key: str) -> int:
        try:
            return int(event.get("id", 0))
        except (TypeError, ValueError):
            return NotificationScheduler.notification_id(key, "stale")

    async def _cancel_events(self, events: dict[str, Any]) -> dict[str, Any]:
        retained: dict[str, Any] = {}
        for key, event in list(events.items()):
            if isinstance(event, dict) and not await self._cancel(
                self._event_id(event, key)
            ):
                retained[key] = event
        return retained

    async def _cancel(self, notification_id: int) -> bool:
        if self._adapter is None or not notification_id:
            return False
        try:
            await self._adapter.cancel(notification_id)
            return True
        except Exception as error:
            logger.warning(
                "Could not cancel task notification %s: %s",
                notification_id,
                error,
            )
            return False

    async def _handle_tap(self, event: Any) -> None:
        if self._on_tap is None:
            return
        data = getattr(event, "data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        if not isinstance(data, dict):
            return
        payload = data.get("payload", data)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if isinstance(task_id, str) and task_id:
            result = self._on_tap(task_id)
            if result is not None:
                await result
