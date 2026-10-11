import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import flet as ft

from app.services.firestore import FirestoreError
from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.study_cache import StudyCache
from app.ui.theme import load_dark_mode, save_dark_mode
from app.ui.workspace import StudyWorkspace


class FakePage:
    def __init__(self) -> None:
        self.dialog: ft.Control | None = None
        self.controls: list[ft.Control] = []

    def update(self, *_: ft.Control) -> None:
        pass

    def show_dialog(self, dialog: ft.Control) -> None:
        self.dialog = dialog

    def pop_dialog(self) -> ft.Control | None:
        dialog = self.dialog
        self.dialog = None
        return dialog

    def clean(self) -> None:
        self.controls.clear()

    def add(self, *controls: ft.Control) -> None:
        self.controls.extend(controls)

    def run_task(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        return None


class WorkspaceUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._cache_directory = tempfile.TemporaryDirectory()
        self.page = FakePage()
        self.workspace = StudyWorkspace(
            self.page,  # type: ignore[arg-type]
            FirebaseAuthService("test-api-key"),
            "test-project",
            on_unauthenticated=lambda: None,
        )
        self.workspace._study_cache = StudyCache(
            Path(self._cache_directory.name) / "study-cache.json"
        )

    def tearDown(self) -> None:
        self._cache_directory.cleanup()

    def test_filters_start_collapsed_and_can_be_toggled_without_resetting(self) -> None:
        screen = self.workspace._task_screen()
        self.assertIsInstance(screen, ft.ListView)
        if not isinstance(screen, ft.ListView):
            self.fail("Tasks screen must be a list view.")
        subject_folders = screen.controls[1]
        filter_panel = screen.controls[3]
        toolbar = screen.controls[2]

        self.assertIsInstance(subject_folders, ft.Container)
        self.assertIsInstance(filter_panel, ft.Container)
        self.assertIsInstance(toolbar, ft.Row)
        if not isinstance(filter_panel, ft.Container):
            self.fail("Filter panel must be a container.")
        if not isinstance(toolbar, ft.Row):
            self.fail("Task toolbar must be a row.")
        filter_button = toolbar.controls[1]
        if not isinstance(filter_button, ft.IconButton):
            self.fail("Filter control must be an icon button.")
        self.assertFalse(filter_panel.visible)
        open_filters = getattr(filter_button, "on_click", None)
        if not callable(open_filters):
            self.fail("Filter control must toggle the filter panel.")
        open_filters()
        self.assertTrue(filter_panel.visible)
        self.assertTrue(self.workspace._filters_expanded)

        self.workspace._task_filter_values["category"] = "exam"
        if not isinstance(filter_panel.content, ft.Column):
            self.fail("Filter panel must contain a column.")
        title_row = filter_panel.content.controls[0]
        if not isinstance(title_row, ft.Row):
            self.fail("Filter panel header must be a row.")
        close_button = title_row.controls[1]
        self.assertIsInstance(close_button, ft.IconButton)
        if not isinstance(close_button, ft.IconButton):
            self.fail("Filter close action must be an icon button.")
        close_filters = getattr(close_button, "on_click", None)
        if not callable(close_filters):
            self.fail("Filter close action must collapse the panel.")
        close_filters()
        self.assertFalse(filter_panel.visible)
        self.assertEqual(self.workspace._task_filter_values["category"], "exam")

    def test_subject_folder_filters_tasks_and_all_tasks_clears_it(self) -> None:
        self.workspace.subject_cache = [
            SimpleNamespace(id="math", title="Mathematics")
        ]
        screen = self.workspace._task_screen()
        if not isinstance(screen, ft.ListView):
            self.fail("Tasks screen must be a list view.")
        subject_folders = screen.controls[1]
        if not isinstance(subject_folders, ft.Container):
            self.fail("Subject folders must be in a container.")
        if not isinstance(subject_folders.content, ft.Row):
            self.fail("Subject folders must scroll horizontally in a row.")

        all_tasks_folder, mathematics_folder = subject_folders.content.controls
        if not isinstance(mathematics_folder, ft.Button):
            self.fail("Each subject must be a tappable folder.")
        open_mathematics = getattr(mathematics_folder, "on_click", None)
        if not callable(open_mathematics):
            self.fail("Subject folder must filter its tasks when tapped.")
        open_mathematics()
        self.assertEqual(self.workspace._task_filter_values["subject_id"], "math")
        self.assertEqual(mathematics_folder.icon, ft.Icons.FOLDER_OPEN)

        if not isinstance(all_tasks_folder, ft.Button):
            self.fail("All tasks must be a tappable folder.")
        show_all_tasks = getattr(all_tasks_folder, "on_click", None)
        if not callable(show_all_tasks):
            self.fail("All tasks folder must clear the subject filter.")
        show_all_tasks()
        self.assertEqual(self.workspace._task_filter_values["subject_id"], "")
        self.assertEqual(all_tasks_folder.icon, ft.Icons.FOLDER_OPEN)

    def test_deadline_picker_is_read_only_and_supports_select_and_clear(self) -> None:
        self.workspace._show_task_dialog()
        dialog = self.page.dialog
        if not isinstance(dialog, ft.AlertDialog):
            self.fail("Task form must open an alert dialog.")
        if not isinstance(dialog.content, ft.Column):
            self.fail("Task dialog content must be a scrollable column.")
        deadline_row = dialog.content.controls[2]
        if not isinstance(deadline_row, ft.Row):
            self.fail("Deadline controls must be grouped in a row.")
        deadline_field = deadline_row.controls[0]
        if not isinstance(deadline_field, ft.TextField):
            self.fail("Deadline must be displayed in a text field.")

        self.assertTrue(deadline_field.read_only)
        open_picker = getattr(deadline_field, "on_click", None)
        if not callable(open_picker):
            self.fail("Deadline field must open its date picker.")
        open_picker()
        picker = self.page.dialog
        if not isinstance(picker, ft.DatePicker):
            self.fail("Deadline field must open a native date picker.")

        picker.value = date(2026, 10, 11)
        picker_changed = getattr(picker, "on_change", None)
        if not callable(picker_changed):
            self.fail("Date picker must handle selected dates.")
        picker_changed(SimpleNamespace(control=picker))
        self.assertEqual(deadline_field.value, "Oct 11, 2026")
        self.assertTrue(deadline_row.controls[2].visible)

        clear_button = deadline_row.controls[2]
        self.assertIsInstance(clear_button, ft.IconButton)
        if not isinstance(clear_button, ft.IconButton):
            self.fail("Deadline clear action must be an icon button.")
        clear_action = getattr(clear_button, "on_click", None)
        if not callable(clear_action):
            self.fail("Deadline clear action must be available.")
        clear_action()
        self.assertEqual(deadline_field.value, "")
        self.assertFalse(deadline_row.controls[2].visible)

    def test_deadline_storage_conversion_keeps_selected_local_date(self) -> None:
        selected_day = date(2026, 10, 11)
        deadline = self.workspace._deadline_for_date(selected_day)

        self.assertIsNotNone(deadline)
        if deadline is None:
            self.fail("Selected task date should be converted to a deadline.")
        self.assertEqual(deadline.astimezone().date(), selected_day)
        self.assertIsNone(self.workspace._deadline_for_date(None))

    def test_calendar_cells_expand_into_seven_even_columns(self) -> None:
        self.workspace.displayed_month = date(2021, 5, 1)
        calendar = self.workspace._calendar_screen()

        self.assertIsInstance(calendar, ft.ListView)
        if not isinstance(calendar, ft.ListView):
            self.fail("Calendar must be a scrollable list.")
        week_rows = calendar.controls[1]
        self.assertIsInstance(week_rows, ft.Column)
        if not isinstance(week_rows, ft.Column):
            self.fail("Calendar weeks must be arranged in a column.")
        self.assertEqual(len(week_rows.controls), 7)
        for row in week_rows.controls:
            self.assertIsInstance(row, ft.Row)
            if not isinstance(row, ft.Row):
                self.fail("Each calendar week must be a row.")
            self.assertEqual(len(row.controls), 7)
            for cell in row.controls:
                self.assertIsInstance(cell, ft.Container)
                if not isinstance(cell, ft.Container):
                    self.fail("Calendar cells must be flexible containers.")
                self.assertTrue(cell.expand)
                self.assertIsNone(cell.width)

    def test_calendar_month_navigation_clamps_selected_day(self) -> None:
        self.workspace.displayed_month = date(2021, 1, 1)
        self.workspace.selected_day = date(2021, 1, 31)

        self.workspace._change_month(1)

        self.assertEqual(self.workspace.displayed_month, date(2021, 2, 1))
        self.assertEqual(self.workspace.selected_day, date(2021, 2, 28))

    def test_appearance_preference_persists_between_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            preference_file = Path(directory) / "preferences.json"
            with patch(
                "app.ui.theme._preferences_path", return_value=preference_file
            ):
                self.assertFalse(load_dark_mode())
                save_dark_mode(True)
                self.assertTrue(load_dark_mode())
                save_dark_mode(False)
                self.assertFalse(load_dark_mode())

    def test_workspace_renders_loading_before_firestore_requests_finish(self) -> None:
        async def exercise() -> None:
            release_requests = asyncio.Event()
            self.workspace.auth._session = AuthSession(
                uid="user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
            )

            class SlowCollection:
                async def get_tasks(self) -> list[Any]:
                    await release_requests.wait()
                    return []

                async def get_subjects(self) -> list[Any]:
                    await release_requests.wait()
                    return []

            collection = SlowCollection()
            self.workspace.tasks = collection  # type: ignore[assignment]
            self.workspace.subjects = collection  # type: ignore[assignment]
            loading = asyncio.create_task(self.workspace.show("home"))
            await asyncio.sleep(0)

            self.assertEqual(len(self.page.controls), 1)
            root = self.page.controls[0]
            self.assertIsInstance(root, ft.Container)
            if not isinstance(root, ft.Container):
                self.fail("Loading content should be a container.")
            loading_column = root.content
            if not isinstance(loading_column, ft.Column):
                self.fail("The loading page should render a centered column.")
            self.assertTrue(
                any(
                    isinstance(control, ft.ProgressRing)
                    for control in loading_column.controls
                )
            )

            release_requests.set()
            await loading

        asyncio.run(exercise())

    def test_navigation_after_startup_uses_cache_without_startup_loader(self) -> None:
        async def exercise() -> None:
            self.workspace.auth._session = AuthSession(
                uid="user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
            )
            self.workspace._load_data = AsyncMock(return_value=([], []))
            await self.workspace.show("home")
            self.assertEqual(self.workspace._startup_state, "ready")
            self.assertEqual(self.workspace._load_data.await_count, 1)

            await self.workspace.show("tasks")
            self.assertEqual(self.workspace.route, "tasks")
            self.assertEqual(self.workspace._load_data.await_count, 1)
            self.assertEqual(self.workspace._startup_state, "ready")
            root = self.page.controls[0]
            self.assertIsInstance(root, ft.Column)

            await self.workspace.show("calendar")
            self.assertEqual(self.workspace.route, "calendar")
            self.assertEqual(self.workspace._load_data.await_count, 1)
            self.assertEqual(self.workspace._startup_state, "ready")

            refresh_started = asyncio.Event()
            finish_refresh = asyncio.Event()

            async def delayed_refresh(
                _: AuthSession,
            ) -> tuple[list[Any], list[Any]]:
                refresh_started.set()
                await finish_refresh.wait()
                return [], []

            self.workspace._load_data = AsyncMock(side_effect=delayed_refresh)
            refresh = asyncio.create_task(
                self.workspace.show("settings", refresh=True)
            )
            await refresh_started.wait()
            self.assertEqual(self.workspace._load_data.await_count, 1)
            self.assertEqual(self.workspace._startup_state, "ready")
            self.assertTrue(self.workspace._data_loading)
            self.assertIsInstance(self.page.controls[0], ft.Column)

            finish_refresh.set()
            await refresh
            self.assertFalse(self.workspace._data_loading)

        asyncio.run(exercise())

    def test_failed_startup_can_retry_without_restoring_startup_loader(self) -> None:
        async def exercise() -> None:
            self.workspace.auth._session = AuthSession(
                uid="user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
            )
            self.workspace._load_data = AsyncMock(
                side_effect=[FirestoreError("offline"), ([], [])]
            )

            await self.workspace.show("home")
            self.assertEqual(self.workspace._startup_state, "error")
            self.assertEqual(self.workspace._data_error, "offline")
            self.assertIsInstance(self.page.controls[0], ft.Column)

            await self.workspace._retry_data_load()
            self.assertEqual(self.workspace._startup_state, "ready")
            self.assertEqual(self.workspace._load_data.await_count, 2)
            self.assertIsInstance(self.page.controls[0], ft.Column)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
