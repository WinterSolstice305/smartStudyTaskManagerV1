import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import flet as ft

from app.models.task import Task
from app.services.firestore import FirestoreDocument, FirestoreError
from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.study_cache import StudyCache
from app.ui.theme import DARK, LIGHT, apply_theme, load_dark_mode, save_dark_mode
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
        self._preferences_patch = patch(
            "app.ui.theme._preferences_path",
            return_value=Path(self._cache_directory.name) / "preferences.json",
        )
        self._preferences_patch.start()
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
        self._preferences_patch.stop()
        self._cache_directory.cleanup()

    @staticmethod
    def _contrast_ratio(foreground: str, background: str) -> float:
        def channel(value: str) -> float:
            value = int(value, 16) / 255
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        def luminance(color: str) -> float:
            color = color.removeprefix("#")
            return (
                0.2126 * channel(color[0:2])
                + 0.7152 * channel(color[2:4])
                + 0.0722 * channel(color[4:6])
            )

        lighter = max(luminance(foreground), luminance(background))
        darker = min(luminance(foreground), luminance(background))
        return (lighter + 0.05) / (darker + 0.05)

    def test_light_and_dark_palettes_have_contrast_for_primary_text(self) -> None:
        for palette in (LIGHT, DARK):
            self.assertGreaterEqual(
                self._contrast_ratio(palette.text, palette.background), 7.0
            )
            self.assertGreaterEqual(
                self._contrast_ratio(palette.secondary_text, palette.surface), 4.5
            )
            self.assertGreaterEqual(
                self._contrast_ratio(palette.on_primary, palette.primary), 4.5
            )

    def test_theme_switching_updates_explicit_color_schemes(self) -> None:
        apply_theme(self.page, False)
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.LIGHT)
        self.assertEqual(self.page.theme.color_scheme.on_surface, LIGHT.text)
        self.assertEqual(self.page.theme.color_scheme.outline, LIGHT.border)

        apply_theme(self.page, True)
        self.assertEqual(self.page.theme_mode, ft.ThemeMode.DARK)
        self.assertEqual(self.page.theme.color_scheme.on_surface, DARK.text)
        self.assertEqual(self.page.theme.color_scheme.outline, DARK.border)

    def test_major_screens_build_in_both_theme_modes(self) -> None:
        session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        for dark_mode in (False, True):
            self.workspace.dark_mode = dark_mode
            apply_theme(self.page, dark_mode)
            for route in ("home", "tasks", "calendar", "settings", "profile"):
                self.workspace.route = route
                screen = self.workspace._build_screen(session)
                self.assertIsInstance(screen, ft.Control)

    def test_chat_templates_submit_their_predefined_prompts(self) -> None:
        self.workspace.auth._session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._data_available = True
        self.workspace._data_uid = "user"
        screen = self.workspace._chatbot_screen()
        if not isinstance(screen, ft.Column):
            self.fail("Assistant screen must be a column.")
        suggestions_panel = screen.controls[1]
        if not isinstance(suggestions_panel, ft.Container):
            self.fail("Suggested prompts must be in a container.")
        if not isinstance(suggestions_panel.content, ft.Column):
            self.fail("Suggested prompts must be arranged in a column.")
        suggestion_row = suggestions_panel.content.controls[1]
        if not isinstance(suggestion_row, ft.Row):
            self.fail("Suggested prompts must be arranged in a row.")

        with patch.object(self.page, "run_task") as run_task:
            for prompt, button in zip(
                self.workspace._chat_suggestions, suggestion_row.controls
            ):
                self.assertIsInstance(button, ft.TextButton)
                if not isinstance(button, ft.TextButton):
                    self.fail("Each suggested prompt must be a text button.")
                self.assertFalse(button.disabled)
                button.on_click(None)
                run_task.assert_called_with(self.workspace._send_chat_message, prompt)
                run_task.reset_mock()

    def test_chat_bubbles_fit_their_text_and_keep_speaker_alignment(self) -> None:
        for speaker, expected_alignment in (
            ("user", ft.MainAxisAlignment.END),
            ("assistant", ft.MainAxisAlignment.START),
        ):
            with self.subTest(speaker=speaker):
                bubble_row = self.workspace._chat_bubble(
                    speaker, "A short chat message."
                )
                self.assertIsInstance(bubble_row, ft.Container)
                if not isinstance(bubble_row, ft.Container):
                    self.fail("Each chat message must be contained.")
                self.assertIsNone(bubble_row.height)
                self.assertIsNone(bubble_row.alignment)
                self.assertIsNone(bubble_row.width)
                self.assertTrue(bubble_row.expand)
                self.assertIsInstance(bubble_row.content, ft.Row)
                if not isinstance(bubble_row.content, ft.Row):
                    self.fail("Speaker alignment must be provided by a row.")
                self.assertEqual(bubble_row.content.alignment, expected_alignment)
                self.assertTrue(bubble_row.content.expand)

                message = bubble_row.content.controls[0]
                self.assertIsInstance(message, ft.Column)
                if not isinstance(message, ft.Column):
                    self.fail("A chat message must contain a label and bubble.")
                self.assertTrue(message.expand)
                message_bubble = message.controls[1]
                self.assertIsInstance(message_bubble, ft.Container)
                if not isinstance(message_bubble, ft.Container):
                    self.fail("The message text must be inside a bubble.")
                self.assertIsNone(message_bubble.height)
                self.assertIsNone(message_bubble.expand)
                self.assertIsNone(message_bubble.alignment)
                self.assertIsNone(message_bubble.width)
                self.assertEqual(message_bubble.padding, 12)
                if speaker == "user":
                    self.assertIsInstance(message_bubble.content, ft.Text)
                    if not isinstance(message_bubble.content, ft.Text):
                        self.fail("User messages must remain plain text.")
                    self.assertEqual(message_bubble.content.value, "A short chat message.")
                    self.assertIsNone(message_bubble.content.max_lines)
                    self.assertFalse(message_bubble.content.no_wrap)
                else:
                    self.assertIsInstance(message_bubble.content, ft.Markdown)
                    if not isinstance(message_bubble.content, ft.Markdown):
                        self.fail("Assistant messages must use Markdown rendering.")
                    self.assertEqual(
                        message_bubble.content.value, "A short chat message."
                    )
                    self.assertEqual(
                        message_bubble.content.extension_set,
                        ft.MarkdownExtensionSet.GITHUB_WEB,
                    )
                    self.assertTrue(message_bubble.content.selectable)
                    self.assertFalse(message_bubble.content.auto_follow_links)
                    self.assertIsNotNone(message_bubble.content.on_tap_link)
                    self.assertFalse(message_bubble.content.shrink_wrap)
                    self.assertFalse(message_bubble.content.fit_content)
                    self.assertIsNone(message_bubble.content.height)
                    self.assertIsNone(message_bubble.content.expand)

    def test_assistant_markdown_creation_failure_falls_back_to_original_text(self) -> None:
        response = "# Study plan\n\n- Review **Data Structures**"
        with self.assertLogs("app.ui.workspace", level="ERROR"):
            with patch(
                "app.ui.workspace.ft.Markdown", side_effect=ValueError("invalid")
            ):
                bubble_row = self.workspace._chat_bubble("assistant", response)

        if not isinstance(bubble_row.content, ft.Row):
            self.fail("The assistant message must keep its row layout.")
        message = bubble_row.content.controls[0]
        if not isinstance(message, ft.Column):
            self.fail("The assistant message must keep its bubble layout.")
        bubble = message.controls[1]
        if not isinstance(bubble, ft.Container):
            self.fail("The assistant response must remain inside a bubble.")
        self.assertIsInstance(bubble.content, ft.Text)
        if not isinstance(bubble.content, ft.Text):
            self.fail("Markdown failures must fall back to plain text.")
        self.assertEqual(bubble.content.value, response)

    def test_assistant_markdown_links_only_open_safe_web_urls(self) -> None:
        bubble_row = self.workspace._chat_bubble("assistant", "See [this link](url).")
        if not isinstance(bubble_row.content, ft.Row):
            self.fail("The assistant message must keep its row layout.")
        message = bubble_row.content.controls[0]
        if not isinstance(message, ft.Column):
            self.fail("The assistant message must keep its bubble layout.")
        bubble = message.controls[1]
        if not isinstance(bubble, ft.Container) or not isinstance(
            bubble.content, ft.Markdown
        ):
            self.fail("Assistant messages must use Markdown rendering.")
        self.assertEqual(
            bubble.content.on_tap_link, self.workspace._open_chat_markdown_link
        )

        with patch.object(self.page, "run_task") as run_task:
            self.workspace._open_chat_markdown_link(
                SimpleNamespace(data="https://example.com/path")
            )
            run_task.assert_called_once()
            self.assertEqual(run_task.call_args.args[0].__name__, "launch_url")
            self.assertEqual(
                run_task.call_args.args[1], "https://example.com/path"
            )

            run_task.reset_mock()
            with self.assertLogs("app.ui.workspace", level="WARNING"):
                self.workspace._open_chat_markdown_link(
                    SimpleNamespace(data="javascript:alert(1)")
                )
            run_task.assert_not_called()

    def test_chat_conversation_expands_and_auto_scrolls(self) -> None:
        self.workspace.auth._session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._chat_history = [
            {"role": "user", "text": "Hello"},
            {"role": "assistant", "text": "How can I help?"},
        ]

        screen = self.workspace._chatbot_screen()
        self.assertIsInstance(screen, ft.Column)
        if not isinstance(screen, ft.Column):
            self.fail("Assistant screen must be a column.")
        messages = screen.controls[2]
        self.assertIsInstance(messages, ft.ListView)
        if not isinstance(messages, ft.ListView):
            self.fail("Conversation messages must use a list view.")
        self.assertTrue(messages.expand)
        self.assertTrue(messages.auto_scroll)

    def test_task_alarm_checkbox_defaults_on_and_preserves_saved_value(self) -> None:
        self.workspace._show_task_dialog()
        dialog = self.page.dialog
        self.assertIsInstance(dialog, ft.AlertDialog)
        if not isinstance(dialog, ft.AlertDialog):
            self.fail("Task form should open in an alert dialog.")
        self.assertIsInstance(dialog.content, ft.Column)
        if not isinstance(dialog.content, ft.Column):
            self.fail("Task form content should be a column.")
        checkbox = next(
            control
            for control in dialog.content.controls
            if isinstance(control, ft.Checkbox)
        )
        self.assertEqual(checkbox.label, "Alarm at due time")
        self.assertTrue(checkbox.value)

        task = Task(
            "task-1",
            "Existing task",
            None,
            alarm_enabled=False,
        )
        self.workspace._show_task_dialog(task)
        dialog = self.page.dialog
        if not isinstance(dialog, ft.AlertDialog) or not isinstance(
            dialog.content, ft.Column
        ):
            self.fail("Editing a task should retain the task form.")
        checkbox = next(
            control
            for control in dialog.content.controls
            if isinstance(control, ft.Checkbox)
        )
        self.assertFalse(checkbox.value)

    def test_new_account_premade_tasks_are_persisted_once(self) -> None:
        async def exercise() -> None:
            self.workspace.auth._session_path = (
                Path(self._cache_directory.name) / "session.json"
            )
            session = AuthSession(
                uid="new-user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
                is_new_account=True,
            )
            self.workspace.auth._session = session
            self.workspace.firestore.read_document = AsyncMock(return_value=None)
            self.workspace.firestore.create_document = AsyncMock(
                return_value="premade_tasks_v1"
            )
            self.workspace.tasks.get_task = AsyncMock(return_value=None)

            async def create_task(**values: Any) -> Task:
                return Task(
                    id=values["task_id"],
                    title=values["title"],
                    deadline=values["deadline"],
                    description=values["description"],
                    priority=values["priority"],
                    category=values["category"],
                    status=values["status"],
                    alarm_enabled=values["alarm_enabled"],
                )

            self.workspace.tasks.create_task = AsyncMock(side_effect=create_task)
            seeded = await self.workspace._seed_premade_example_tasks(session)

            self.assertEqual(
                [task.title for task in seeded],
                ["Review Data Structures", "Finish Research Paper"],
            )
            self.assertEqual(
                [task.description for task in seeded],
                [
                    "Review stacks, queues, and trees. Solve at least five practice problems.",
                    "Complete the introduction and methodology sections, then review the draft.",
                ],
            )
            self.assertTrue(all(task.deadline is None for task in seeded))
            self.assertTrue(all(not task.alarm_enabled for task in seeded))
            self.assertEqual(
                [task.category for task in seeded], ["Study", "Assignment"]
            )
            self.workspace.firestore.create_document.assert_awaited_once_with(
                "workspace_metadata",
                {"premade_tasks_seeded": True},
                document_id="premade_tasks_v1",
            )
            current_session = self.workspace.auth.session
            assert current_session is not None
            self.assertFalse(current_session.is_new_account)

            self.workspace.auth._session = AuthSession(
                uid="new-user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
                is_new_account=True,
            )
            self.workspace.firestore.read_document = AsyncMock(
                return_value=FirestoreDocument(
                    "premade_tasks_v1", {"premade_tasks_seeded": True}
                )
            )
            self.workspace.tasks.get_task.reset_mock()
            self.workspace.tasks.create_task.reset_mock()

            self.assertEqual(
                await self.workspace._seed_premade_example_tasks(session), []
            )
            self.workspace.tasks.get_task.assert_not_awaited()
            self.workspace.tasks.create_task.assert_not_awaited()
            self.workspace.firestore.create_document.assert_awaited_once()
            current_session = self.workspace.auth.session
            assert current_session is not None
            self.assertFalse(current_session.is_new_account)

        asyncio.run(exercise())

    def test_premade_task_retry_reuses_tasks_created_before_failure(self) -> None:
        async def exercise() -> None:
            session = AuthSession(
                uid="new-user",
                email="student@example.com",
                id_token="token",
                refresh_token="refresh-token",
                expires_in="3600",
                is_new_account=True,
            )
            self.workspace.auth._session = session
            existing = Task(
                id="premade-review-data-structures",
                title="Review Data Structures",
                deadline=None,
                description=(
                    "Review stacks, queues, and trees. Solve at least five "
                    "practice problems."
                ),
                priority="medium",
                category="Study",
                alarm_enabled=False,
            )
            self.workspace.firestore.read_document = AsyncMock(return_value=None)
            self.workspace.firestore.create_document = AsyncMock(
                return_value="premade_tasks_v1"
            )
            self.workspace.tasks.get_task = AsyncMock(
                side_effect=[existing, None]
            )
            self.workspace.tasks.create_task = AsyncMock(
                return_value=Task(
                    id="premade-finish-research-paper",
                    title="Finish Research Paper",
                    deadline=None,
                    priority="high",
                    category="Assignment",
                    alarm_enabled=False,
                )
            )

            seeded = await self.workspace._seed_premade_example_tasks(session)

            self.assertEqual(len(seeded), 2)
            self.workspace.tasks.create_task.assert_awaited_once()
            task_call = self.workspace.tasks.create_task.await_args
            assert task_call is not None
            self.assertEqual(task_call.kwargs["task_id"], "premade-finish-research-paper")
            self.workspace.firestore.create_document.assert_awaited_once()

        asyncio.run(exercise())

    def test_chat_availability_and_sending_states_are_visible(self) -> None:
        self.workspace.auth._session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._data_available = True
        self.workspace._data_uid = "user"
        screen = self.workspace._chatbot_screen()
        if not isinstance(screen, ft.Column):
            self.fail("Assistant screen must be a column.")
        header = screen.controls[0]
        if not isinstance(header, ft.Row) or not isinstance(
            header.controls[1], ft.Column
        ):
            self.fail("Assistant title must include its status indicator.")
        availability = header.controls[1].controls[2]
        self.assertIsInstance(availability, ft.Row)
        if not isinstance(availability, ft.Row):
            self.fail("AI availability must be shown in a row.")
        self.assertEqual(
            availability.controls[1].value, "AI availability not checked"
        )

        self.workspace._ai_availability = "unavailable"
        self.workspace._chat_loading = True
        screen = self.workspace._chatbot_screen()
        if not isinstance(screen, ft.Column):
            self.fail("Assistant screen must be a column.")
        header = screen.controls[0]
        if not isinstance(header, ft.Row) or not isinstance(
            header.controls[1], ft.Column
        ):
            self.fail("Assistant title must include its status indicator.")
        availability = header.controls[1].controls[2]
        self.assertIsInstance(availability, ft.Row)
        if not isinstance(availability, ft.Row):
            self.fail("AI availability must be shown in a row.")
        self.assertEqual(
            availability.controls[1].value, "Reconnecting to AI service…"
        )
        composer = screen.controls[3]
        if not isinstance(composer, ft.Row):
            self.fail("Message composer must be a row.")
        text_field = composer.controls[0]
        self.assertIsInstance(text_field, ft.TextField)
        if not isinstance(text_field, ft.TextField):
            self.fail("Composer must include a text field.")
        self.assertTrue(text_field.disabled)
        send_button = composer.controls[1]
        self.assertIsInstance(send_button, ft.Button)
        if not isinstance(send_button, ft.Button):
            self.fail("Composer must include a send button.")
        self.assertIsInstance(send_button.content, ft.ProgressRing)
        self.assertTrue(send_button.disabled)
        self.assertEqual(send_button.width, 96)
        self.assertEqual(send_button.height, 48)

    def test_chat_composer_updates_send_state_and_uses_current_message(self) -> None:
        self.workspace.auth._session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._data_available = True
        self.workspace._data_uid = "user"
        screen = self.workspace._chatbot_screen()
        if not isinstance(screen, ft.Column):
            self.fail("Assistant screen must be a column.")
        composer = screen.controls[3]
        if not isinstance(composer, ft.Row):
            self.fail("Message composer must be a row.")
        text_field, send_button = composer.controls
        self.assertIsInstance(text_field, ft.TextField)
        self.assertIsInstance(send_button, ft.Button)
        if not isinstance(text_field, ft.TextField) or not isinstance(
            send_button, ft.Button
        ):
            self.fail("Composer must contain a text field and send button.")
        self.assertEqual(send_button.width, 96)
        self.assertEqual(send_button.height, 48)

        text_field.on_change(
            SimpleNamespace(control=SimpleNamespace(value="Review chapter 3"))
        )
        self.assertEqual(self.workspace._chat_message, "Review chapter 3")
        self.assertFalse(send_button.disabled)

        with patch.object(self.page, "run_task") as run_task:
            send_button.on_click(None)
            run_task.assert_called_once_with(
                self.workspace._send_chat_message, "Review chapter 3"
            )

        text_field.on_change(SimpleNamespace(control=SimpleNamespace(value="   ")))
        self.assertTrue(send_button.disabled)

    def test_navigation_bar_is_safe_area_aware_and_centered(self) -> None:
        navigation = self.workspace._navigation_bar()
        self.assertEqual(navigation.height, 80)
        self.assertEqual(
            navigation.label_behavior, ft.NavigationBarLabelBehavior.ALWAYS_SHOW
        )
        self.assertEqual(navigation.label_padding, ft.Padding(0, 2, 0, 6))
        self.assertEqual(navigation.bgcolor, LIGHT.surface)

        session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._render(session)
        root = self.page.controls[0]
        self.assertIsInstance(root, ft.Column)
        if isinstance(root, ft.Column):
            self.assertIsInstance(root.controls[-1], ft.SafeArea)

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

    def test_scrollable_pages_attach_pull_to_refresh_handlers(self) -> None:
        session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace.auth._session = session
        self.workspace.route = "tasks"
        screen = self.workspace._build_screen(session)
        self.assertIsInstance(screen, ft.ListView)
        self.assertTrue(callable(getattr(screen, "on_scroll", None)))

        self.workspace._pull_refresh_distance = 60
        indicator = self.workspace._pull_refresh_indicator()
        self.assertEqual(indicator.height, 48)

    def test_safe_cache_cleanup_preserves_unrelated_user_snapshots(self) -> None:
        self.workspace.auth._session = AuthSession(
            uid="user",
            email="student@example.com",
            id_token="token",
            refresh_token="refresh-token",
            expires_in="3600",
        )
        self.workspace._study_cache.save("user", [], [])
        self.workspace._study_cache.save("guest", [], [])
        self.workspace._study_cache.save("other-user", [], [])

        self.workspace._safe_disposable_cache_cleanup(uid="user")

        self.assertIsNone(self.workspace._study_cache.load("user"))
        self.assertIsNone(self.workspace._study_cache.load("guest"))
        self.assertIsNotNone(self.workspace._study_cache.load("other-user"))


if __name__ == "__main__":
    unittest.main()
