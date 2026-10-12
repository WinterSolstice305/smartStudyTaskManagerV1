import asyncio
import logging
import time as time_module
from calendar import month_name, monthrange
from datetime import date, datetime, time, timezone
from typing import Any

import flet as ft

from app.models import DocumentNotFoundError, ModelValidationError
from app.models.subject import Subject
from app.models.task import Task
from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.firestore import (
    AuthenticationRequiredError,
    FirestoreError,
    FirestoreService,
)
from app.services.gemini import (
    GeminiServiceError,
    TaskRecommendationResult,
    chat_about_tasks,
    generate_task_recommendations,
)
from app.services.subject_service import SubjectService
from app.services.study_cache import StudyCache
from app.services.task_service import TaskService
from app.ui.task_views import filter_tasks, month_grid, sort_tasks, tasks_for_date
from app.ui.theme import (
    apply_theme,
    colors_for,
    load_dark_mode,
    save_dark_mode,
)


logger = logging.getLogger(__name__)


class StudyWorkspace:
    _ROUTES = ["home", "tasks", "calendar", "settings"]
    _NAVIGATION_ROUTES = ["home", "tasks", "calendar", "settings"]
    _PRIORITIES = ["high", "medium", "low"]
    _STATUSES = ["pending", "in_progress", "completed"]
    _SORTS = {
        "Deadline (soonest)": "deadline_asc",
        "Deadline (latest)": "deadline_desc",
        "Priority (highest)": "priority_high",
        "Priority (lowest)": "priority_low",
        "Title (A–Z)": "title",
    }

    def __init__(
        self,
        page: ft.Page,
        auth: FirebaseAuthService,
        project_id: str,
        on_unauthenticated: Any,
    ) -> None:
        self.page = page
        self.auth = auth
        self.firestore = FirestoreService(auth, project_id)
        self.subjects = SubjectService(self.firestore)
        self.tasks = TaskService(self.firestore, self.subjects)
        self._study_cache = StudyCache()
        self.on_unauthenticated = on_unauthenticated
        self.route = "home"
        self.task_cache: list[Task] = []
        self.subject_cache: list[Subject] = []
        self.selected_day = date.today()
        self.displayed_month = date.today().replace(day=1)
        self.dark_mode = False
        self._data_uid: str | None = None
        self._data_loading = False
        self._data_available = False
        self._data_error = ""
        self._offline_mode = False
        self._startup_state = "initializing"
        self._recommendation_loading = False
        self._recommendation_request_id = 0
        self._recommendation_result: TaskRecommendationResult | None = None
        self._recommendation_error = ""
        self._chat_loading = False
        self._chat_request_id = 0
        self._chat_message = ""
        self._chat_response = ""
        self._chat_error = ""
        self.dark_mode = load_dark_mode()
        self._load_request_id = 0
        self._loading_status: ft.Text | None = None
        self._filters_expanded = False
        self._task_filter_values = {
            "subject_id": "",
            "status": "",
            "priority": "",
            "category": "",
            "ordering": "deadline_asc",
        }
        apply_theme(page, self.dark_mode)

    async def show(
        self,
        route: str | None = None,
        notice: str = "",
        *,
        refresh: bool = False,
    ) -> None:
        if self.auth.session is None:
            self._load_request_id += 1
            self._data_loading = False
            self._clear_account_data()
            self.on_unauthenticated()
            return
        if route in (*self._ROUTES, "profile"):
            self.route = route
        session = self.auth.session
        if session is None:
            self._data_loading = False
            self._clear_account_data()
            self.on_unauthenticated()
            return
        account_changed = self._data_uid != session.uid
        if (
            self._startup_state != "initializing"
            and not account_changed
            and not refresh
        ):
            self._render(session, notice=notice, error=self._data_error)
            return

        self._load_request_id += 1
        load_request_id = self._load_request_id
        self._invalidate_ai_requests()
        self._data_loading = True
        initial_startup = self._startup_state == "initializing"
        if account_changed:
            self._clear_account_data()
            self._data_uid = session.uid
            self._offline_mode = False
        cached_data = self._study_cache.load(session.uid) if initial_startup else None
        if cached_data is not None:
            self.task_cache, self.subject_cache = cached_data
            self._data_available = True
            self._offline_mode = False
            self.firestore.seed_offline_snapshot(session.uid, "tasks", [self.firestore_document(task.id, task.to_firestore()) for task in self.task_cache])
            self.firestore.seed_offline_snapshot(session.uid, "subjects", [self.firestore_document(subject.id, subject.to_firestore()) for subject in self.subject_cache])
            self._render(
                session,
                notice="Showing saved tasks while checking for updates...",
            )
        if initial_startup:
            if cached_data is None:
                self._render_loading()
            slow_status = asyncio.create_task(
                self._show_slow_load_status(session.uid, load_request_id)
            )
        else:
            slow_status = None
            self._render(session, notice=notice, error=self._data_error)
        error_message = ""
        started_at = time_module.perf_counter()
        logger.info(
            "%s study data for the authenticated workspace.",
            "Initializing" if initial_startup else "Refreshing",
        )
        try:
            self.task_cache, self.subject_cache = await self._load_data(session)
            if load_request_id != self._load_request_id:
                return
            self._data_available = True
            self._offline_mode = self.firestore.offline
            self._data_error = ""
            self._startup_state = "ready"
            self._study_cache.save(session.uid, self.task_cache, self.subject_cache)
            logger.info(
                "Study data %s in %.2f seconds (%d tasks, %d subjects).",
                "initialized" if initial_startup else "refreshed",
                time_module.perf_counter() - started_at,
                len(self.task_cache),
                len(self.subject_cache),
            )
        except AuthenticationRequiredError:
            if load_request_id != self._load_request_id:
                return
            self.task_cache = []
            self.subject_cache = []
            self._data_uid = None
            self._data_loading = False
            self._data_available = False
            self._startup_state = "ready"
            self._clear_ai_state()
            self.on_unauthenticated()
            return
        except FirestoreError as error:
            if load_request_id != self._load_request_id:
                return
            logger.warning(
                "Study data loading failed after %.2f seconds: %s",
                time_module.perf_counter() - started_at,
                error,
            )
            error_message = str(error)
            self._offline_mode = "Could not reach" in error_message or "internet connection" in error_message
            if account_changed:
                self.task_cache = []
                self.subject_cache = []
        except (ModelValidationError, ValueError) as error:
            if load_request_id != self._load_request_id:
                return
            logger.exception("Saved study data could not be validated.")
            error_message = f"Could not read saved study data: {error}"
            if account_changed:
                self.task_cache = []
                self.subject_cache = []
        finally:
            if slow_status is not None:
                slow_status.cancel()
        if load_request_id == self._load_request_id:
            self._data_loading = False
            if error_message:
                self._data_error = error_message
                if initial_startup:
                    self._startup_state = "error"
            self._render(session, notice=notice, error=self._data_error)

    async def _retry_data_load(self) -> None:
        await self.show(self.route, refresh=True)

    async def _show_slow_load_status(self, uid: str, request_id: int) -> None:
        await asyncio.sleep(5)
        if (
            self._data_loading
            and self._load_request_id == request_id
            and self.auth.session is not None
            and self.auth.session.uid == uid
            and self._loading_status is not None
        ):
            self._loading_status.value = (
                "Still connecting. This can take a moment on a slow network."
            )
            self.page.update()

    def _render_loading(self) -> None:
        palette = colors_for(self.dark_mode)
        self._loading_status = ft.Text(
            "Loading your tasks and subjects...",
            color=palette.secondary_text,
            text_align=ft.TextAlign.CENTER,
        )
        self.page.clean()
        self.page.add(
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(
                            ft.Icons.AUTO_STORIES,
                            size=42,
                            color=palette.primary,
                        ),
                        ft.Text(
                            "Smart Study Task Manager",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=palette.text,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.ProgressRing(color=palette.primary),
                        self._loading_status,
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=18,
                ),
                alignment=ft.Alignment.CENTER,
                bgcolor=palette.background,
                expand=True,
            )
        )

    async def _load_data(self, session: AuthSession) -> tuple[list[Task], list[Subject]]:
        if self.auth.session is None or self.auth.session.uid != session.uid:
            raise AuthenticationRequiredError(
                "Your sign-in state changed. Sign in again to continue."
            )
        tasks, subjects = await self._load_collections()
        if self.auth.session is None or self.auth.session.uid != session.uid:
            raise AuthenticationRequiredError(
                "Your sign-in state changed. Sign in again to continue."
            )
        return tasks, subjects

    async def _load_collections(self) -> tuple[list[Task], list[Subject]]:
        import asyncio

        self.firestore.offline = False
        tasks, subjects = await asyncio.gather(
            self.tasks.get_tasks(), self.subjects.get_subjects()
        )
        return tasks, subjects

    @staticmethod
    def firestore_document(document_id: str, data: dict[str, Any]) -> Any:
        from app.services.firestore import FirestoreDocument

        return FirestoreDocument(document_id, data)

    def _render(
        self, session: AuthSession, *, notice: str = "", error: str = ""
    ) -> None:
        title = {
            "home": "Smart Study Task Manager",
            "tasks": "My Tasks",
            "calendar": "Calendar",
            "settings": "Settings",
            "profile": "Profile",
        }[self.route]
        header = ft.Row(
            controls=[
                ft.Text(title, size=22, weight=ft.FontWeight.BOLD, expand=True),
                ft.IconButton(
                    icon=ft.Icons.PERSON,
                    tooltip="Profile",
                    on_click=lambda _: self.page.run_task(self.show, "profile"),
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        body = self._build_screen(session)
        status_controls: list[ft.Control] = []
        if notice:
            status_controls.append(
                ft.Text(notice, color=self._success_text_color(), selectable=True)
            )
        current_error = error or self._data_error
        if self._data_loading:
            status_controls.append(
                ft.Row(
                    controls=[
                        ft.ProgressRing(width=16, height=16, stroke_width=2),
                        ft.Text(
                            "Refreshing your study data...",
                            color=self._secondary_text_color(),
                        ),
                    ],
                    spacing=8,
                )
            )
        if current_error:
            status_controls.append(
                ft.Text(
                    current_error,
                    color=self._error_text_color(),
                    selectable=True,
                )
            )
            status_controls.append(
                ft.TextButton(
                    "Retry",
                    icon=ft.Icons.REFRESH,
                    on_click=lambda _: self.page.run_task(self._retry_data_load),
                )
            )
        self.page.clean()
        self.page.add(
            ft.Column(
                controls=[
                    ft.Container(header, padding=ft.Padding(16, 12, 8, 8)),
                    *status_controls,
                    ft.Container(content=body, expand=True, padding=ft.Padding(16, 4, 16, 12)),
                    self._navigation_bar(),
                ],
                spacing=0,
                expand=True,
            )
        )

    def _surface_color(self) -> str:
        return colors_for(self.dark_mode).surface

    def _raised_surface_color(self) -> str:
        return colors_for(self.dark_mode).elevated_surface

    def _accent_surface_color(self) -> str:
        return colors_for(self.dark_mode).accent_surface

    def _secondary_text_color(self) -> str:
        return colors_for(self.dark_mode).secondary_text

    def _error_text_color(self) -> str:
        return colors_for(self.dark_mode).error

    def _success_text_color(self) -> str:
        return colors_for(self.dark_mode).accent

    def _navigation_bar(self) -> ft.NavigationBar:
        selected_index = (
            self._ROUTES.index(self.route) if self.route in self._ROUTES else 0
        )
        return ft.NavigationBar(
            selected_index=selected_index,
            height=64,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.HOME, label="Home"),
                ft.NavigationBarDestination(icon=ft.Icons.TASK, label="Tasks"),
                ft.NavigationBarDestination(
                    icon=ft.Icons.CALENDAR_MONTH, label="Calendar"
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SETTINGS, label="Settings"
                ),
            ],
            on_change=self._on_navigation_change,
        )

    def _on_navigation_change(self, event: Any) -> None:
        selected_index = event.control.selected_index
        if not 0 <= selected_index < len(self._NAVIGATION_ROUTES):
            return
        self.route = self._NAVIGATION_ROUTES[selected_index]
        if self.auth.session is not None:
            self._render(self.auth.session, error=self._data_error)

    def _build_screen(self, session: AuthSession) -> ft.Control:
        if self.route == "home":
            return self._dashboard()
        if self.route == "tasks":
            return self._task_screen()
        if self.route == "calendar":
            return self._calendar_screen()
        if self.route == "settings":
            return self._settings_screen()
        return self._profile_screen(session)

    def _dashboard(self) -> ft.Control:
        today = date.today()
        overdue = [
            task
            for task in self.task_cache
            if task.deadline is not None
            and task.deadline.astimezone().date() < today
            and task.status != "completed"
        ]
        upcoming = [
            task
            for task in self.task_cache
            if task.deadline is not None
            and task.deadline.astimezone().date() >= today
        ]
        upcoming.sort(key=lambda task: task.deadline or datetime.max.replace(tzinfo=timezone.utc))
        completed = sum(task.status == "completed" for task in self.task_cache)
        total = len(self.task_cache)
        progress = completed / total if total else 0
        return ft.ListView(
            controls=[
                ft.Text(f"{completed} of {total} tasks completed", size=16),
                ft.ProgressBar(value=progress),
                self._section("Overdue", overdue[:5], "No overdue tasks."),
                self._section("Upcoming", upcoming[:5], "No upcoming tasks."),
                ft.Container(
                    content=self._recommendation_panel(),
                    padding=16,
                    bgcolor=self._accent_surface_color(),
                    border_radius=12,
                ),
                self._chat_panel(),
                ft.Button(
                    content="View all tasks",
                    on_click=lambda _: self.page.run_task(self.show, "tasks"),
                ),
            ],
            spacing=14,
            expand=True,
        )

    def _recommendation_panel(self) -> ft.Control:
        is_guest = self.auth.session is not None and self.auth.session.is_guest
        controls: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Text("AI Task Recommendations", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Unavailable in guest mode" if is_guest else "",
                        color=self._secondary_text_color(),
                        italic=True,
                    ),
                ],
                spacing=8,
            )
        ]
        if is_guest:
            controls.append(ft.Text("Unavailable in guest mode"))
        elif self._offline_mode:
            controls.append(ft.Text("AI features are unavailable offline."))
        elif self._recommendation_loading:
            controls.extend(
                [
                    ft.ProgressBar(),
                    ft.Text("Reviewing your incomplete tasks…"),
                ]
            )
        else:
            if not self._data_available:
                controls.append(
                    ft.Text(
                        "Load your study data successfully before requesting "
                        "recommendations."
                    )
                )
            elif self._recommendation_error:
                controls.append(
                    ft.Text(self._recommendation_error, color=self._error_text_color())
                )
            elif self._recommendation_result is None:
                controls.append(
                    ft.Text(
                        "Get a short, deadline-aware list of tasks to work on next."
                    )
                )
            else:
                controls.append(ft.Text(self._recommendation_result.summary))
                if self._recommendation_result.context_limited:
                    controls.append(
                        ft.Text(
                            "Suggestions use the 40 most urgent incomplete tasks.",
                            size=12,
                        )
                    )
                if self._recommendation_result.recommendations:
                    controls.extend(
                        ft.Container(
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        recommendation.title,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(recommendation.reason, selectable=True),
                                ],
                                spacing=4,
                            ),
                            padding=10,
                            bgcolor=self._raised_surface_color(),
                            border_radius=8,
                        )
                        for recommendation in self._recommendation_result.recommendations
                    )
                else:
                    controls.append(
                        ft.Text("There are no task recommendations to show.")
                    )
            controls.append(
                ft.Button(
                    content=(
                        "Refresh recommendations"
                        if self._recommendation_result is not None
                        else "Get recommendations"
                    ),
                    icon=ft.Icons.AUTO_AWESOME,
                    disabled=(is_guest or self._data_loading or not self._data_available),
                    on_click=lambda _: self.page.run_task(
                        self._request_recommendations
                    ),
                )
            )
        return ft.Column(controls=controls, spacing=8)

    def _chat_panel(self) -> ft.Control:
        is_guest = self.auth.session is not None and self.auth.session.is_guest
        controls: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Text("Study Planning Assistant", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Unavailable in guest mode" if is_guest else "",
                        color=self._secondary_text_color(),
                        italic=True,
                    ),
                ],
                spacing=8,
            ),
            ft.Text(
                "Ask about your current deadlines, workload, or what to study next."
            ),
        ]
        if is_guest:
            controls.append(ft.Text("Unavailable in guest mode"))
        elif self._offline_mode:
            controls.append(ft.Text("AI features are unavailable offline."))
        if not is_guest and not self._offline_mode and not self._data_available:
            controls.append(
                ft.Text("Your study data is unavailable. Retry loading it to chat.")
            )
        elif not any(task.status.casefold() != "completed" for task in self.task_cache):
            controls.append(
                ft.Text(
                    "You have no incomplete tasks. The assistant can still offer "
                    "general study-planning help."
                )
            )
        if self._chat_loading and not is_guest and not self._offline_mode:
            controls.extend([ft.ProgressBar(), ft.Text("Thinking…")])
        elif self._chat_error and not is_guest and not self._offline_mode:
            controls.append(ft.Text(self._chat_error, color=self._error_text_color()))
        elif self._chat_response and not is_guest and not self._offline_mode:
            controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Markdown(
                                self._chat_response,
                                selectable=True,
                                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                            )
                        ],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    height=360,
                    padding=12,
                    bgcolor=self._raised_surface_color(),
                    border_radius=8,
                )
            )
        controls.extend(
            [
                ft.TextField(
                    label="Ask about your study workload",
                    value=self._chat_message,
                    multiline=True,
                    min_lines=2,
                    max_lines=4,
                    disabled=(
                        is_guest or self._offline_mode
                        or
                        self._chat_loading
                        or self._data_loading
                        or not self._data_available
                    ),
                    on_change=lambda event: setattr(
                        self, "_chat_message", event.control.value or ""
                    ),
                ),
                ft.Button(
                    content="Retry" if self._chat_error else "Send",
                    icon=ft.Icons.SEND,
                    disabled=(
                        is_guest or self._offline_mode
                        or
                        self._chat_loading
                        or self._data_loading
                        or not self._data_available
                    ),
                    on_click=lambda _: self.page.run_task(
                        self._send_chat_message, self._chat_message
                    ),
                ),
            ]
        )
        return ft.Container(
            content=ft.Column(controls=controls, spacing=8),
            padding=16,
            bgcolor=self._accent_surface_color(),
            border_radius=12,
        )

    async def _request_recommendations(self) -> None:
        session = self.auth.session
        if (
            session is None
            or session.is_guest
            or self._offline_mode
            or self._data_loading
            or not self._data_available
            or self._recommendation_loading
            or self._data_uid != session.uid
        ):
            return
        request_id = self._recommendation_request_id
        tasks = tuple(self.task_cache)
        subjects = tuple(self.subject_cache)
        self._recommendation_loading = True
        self._recommendation_error = ""
        self._render(session)
        try:
            result = await generate_task_recommendations(
                tasks, subjects, id_token=session.id_token
            )
        except GeminiServiceError as error:
            if self._recommendation_request_is_current(session.uid, request_id):
                self._recommendation_error = str(error)
        else:
            if self._recommendation_request_is_current(session.uid, request_id):
                self._recommendation_result = result
        finally:
            if self._recommendation_request_is_current(session.uid, request_id):
                self._recommendation_loading = False
                if self.route == "home":
                    self._render(session)

    async def _send_chat_message(self, message: str) -> None:
        session = self.auth.session
        if (
            session is None
            or session.is_guest
            or self._offline_mode
            or self._data_loading
            or not self._data_available
            or self._chat_loading
            or self._data_uid != session.uid
        ):
            return
        request_id = self._chat_request_id
        tasks = tuple(self.task_cache)
        subjects = tuple(self.subject_cache)
        self._chat_message = message
        self._chat_loading = True
        self._chat_error = ""
        self._render(session)
        try:
            response = await chat_about_tasks(
                message, tasks, subjects, id_token=session.id_token
            )
        except GeminiServiceError as error:
            if self._chat_request_is_current(session.uid, request_id):
                self._chat_error = str(error)
        else:
            if self._chat_request_is_current(session.uid, request_id):
                self._chat_response = response
        finally:
            if self._chat_request_is_current(session.uid, request_id):
                self._chat_loading = False
                if self.route == "home":
                    self._render(session)

    def _recommendation_request_is_current(self, uid: str, request_id: int) -> bool:
        return (
            self.auth.session is not None
            and self.auth.session.uid == uid
            and self._data_uid == uid
            and not self._data_loading
            and self._recommendation_request_id == request_id
        )

    def _chat_request_is_current(self, uid: str, request_id: int) -> bool:
        return (
            self.auth.session is not None
            and self.auth.session.uid == uid
            and self._data_uid == uid
            and not self._data_loading
            and self._chat_request_id == request_id
        )

    def _invalidate_ai_requests(self) -> None:
        self._recommendation_request_id += 1
        self._chat_request_id += 1
        self._recommendation_loading = False
        self._chat_loading = False

    def _clear_account_data(self) -> None:
        self.task_cache = []
        self.subject_cache = []
        self._data_uid = None
        self._data_available = False
        self._data_error = ""
        self._clear_ai_state()

    def _clear_ai_state(self) -> None:
        self._recommendation_result = None
        self._recommendation_error = ""
        self._chat_message = ""
        self._chat_response = ""
        self._chat_error = ""

    def _section(self, title: str, tasks: list[Task], empty_text: str) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
                *(
                    [self._task_tile(task, compact=True) for task in tasks]
                    if tasks
                    else [ft.Text(empty_text)]
                ),
            ],
            spacing=8,
        )

    def _task_screen(self) -> ft.Control:
        subject_folders = self._subject_folder_strip()
        subject_filter = ft.Dropdown(
            label="Subject",
            value=self._task_filter_values["subject_id"],
            options=[
                ft.DropdownOption(key="", text="All subjects"),
                *[
                    ft.DropdownOption(key=subject.id, text=subject.title)
                    for subject in self.subject_cache
                ],
            ],
            on_select=lambda event: self._set_task_filter(
                "subject_id", event.control.value or ""
            ),
            expand=True,
        )
        status_filter = ft.Dropdown(
            label="Status",
            value=self._task_filter_values["status"],
            options=[
                ft.DropdownOption(key="", text="All statuses"),
                *[
                    ft.DropdownOption(key=status, text=status.replace("_", " ").title())
                    for status in self._STATUSES
                ],
            ],
            on_select=lambda event: self._set_task_filter(
                "status", event.control.value or ""
            ),
            expand=True,
        )
        priority_filter = ft.Dropdown(
            label="Priority",
            value=self._task_filter_values["priority"],
            options=[
                ft.DropdownOption(key="", text="All priorities"),
                *[
                    ft.DropdownOption(key=value, text=value.title())
                    for value in self._PRIORITIES
                ],
            ],
            on_select=lambda event: self._set_task_filter(
                "priority", event.control.value or ""
            ),
            expand=True,
        )
        category_values = sorted({task.category for task in self.task_cache})
        category_filter = ft.Dropdown(
            label="Category",
            value=self._task_filter_values["category"],
            options=[
                ft.DropdownOption(key="", text="All categories"),
                *[
                    ft.DropdownOption(key=value, text=value)
                    for value in category_values
                ],
            ],
            on_select=lambda event: self._set_task_filter(
                "category", event.control.value or ""
            ),
            expand=True,
        )
        sort_control = ft.Dropdown(
            label="Sort by",
            value=self._task_filter_values["ordering"],
            options=[
                ft.DropdownOption(key=value, text=label)
                for label, value in self._SORTS.items()
            ],
            on_select=lambda event: self._set_task_filter(
                "ordering", event.control.value or "deadline_asc"
            ),
            expand=True,
        )
        task_list = ft.Column(spacing=8)
        filters = [subject_filter, status_filter, priority_filter, category_filter]

        def update_list(update_page: bool = True) -> None:
            selected = filter_tasks(
                self.task_cache,
                subject_id=self._task_filter_values["subject_id"],
                status=self._task_filter_values["status"],
                priority=self._task_filter_values["priority"],
                category=self._task_filter_values["category"],
            )
            selected = sort_tasks(
                selected, self._task_filter_values["ordering"] or "deadline_asc"
            )
            task_list.controls.clear()
            if selected:
                task_list.controls.extend(self._task_tile(task) for task in selected)
            else:
                task_list.controls.append(
                    ft.Text(
                        "No tasks match these filters."
                        if self.task_cache
                        else "No tasks yet. Add a task to get started."
                    )
                )
            if update_page:
                self.page.update()

        self._active_filter_controls = filters + [sort_control]
        self._active_task_list = task_list
        self._active_update_tasks = update_list
        update_list(update_page=False)
        has_active_filters = any(
            self._task_filter_values[key]
            for key in ("subject_id", "status", "priority", "category")
        ) or self._task_filter_values["ordering"] != "deadline_asc"

        filter_button = ft.IconButton(
            icon=ft.Icons.FILTER_ALT,
            selected=self._filters_expanded or has_active_filters,
            icon_color=(
                colors_for(self.dark_mode).primary
                if self._filters_expanded or has_active_filters
                else self._secondary_text_color()
            ),
            tooltip="Filter and sort tasks",
        )
        self._active_filter_button = filter_button
        filter_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Filter and sort",
                                size=17,
                                weight=ft.FontWeight.BOLD,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                tooltip="Close filters",
                                on_click=lambda _=None: self._toggle_task_filters(False),
                            ),
                            ft.TextButton(
                                "Reset",
                                icon=ft.Icons.FILTER_ALT_OFF,
                                tooltip="Reset filters and sorting",
                                on_click=lambda _: self._reset_filters(),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.ResponsiveRow(
                        controls=[
                            ft.Container(control, col={"xs": 12, "md": 6})
                            for control in filters
                        ],
                        columns=12,
                        spacing=10,
                        run_spacing=2,
                    ),
                    sort_control,
                ],
                spacing=6,
            ),
            padding=12,
            bgcolor=self._surface_color(),
            border_radius=12,
            visible=self._filters_expanded,
        )
        self._active_filter_panel = filter_section
        filter_button.on_click = lambda _=None: self._toggle_task_filters(
            not self._filters_expanded
        )
        return ft.ListView(
            controls=[
                ft.Row(
                    controls=[
                        ft.Button(
                            content="Add task",
                            icon=ft.Icons.ADD,
                            on_click=lambda _: self._show_task_dialog(),
                            expand=True,
                        ),
                        ft.OutlinedButton(
                            content="Add subject",
                            on_click=lambda _: self._show_subject_dialog(),
                            expand=True,
                        ),
                    ]
                ),
                subject_folders,
                ft.Row(
                    controls=[
                        ft.Text(
                            "Your tasks",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                        ),
                        filter_button,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                filter_section,
                task_list,
            ],
            spacing=8,
            expand=True,
        )

    def _apply_task_filters(self) -> None:
        update = getattr(self, "_active_update_tasks", None)
        if update:
            update()
        self._refresh_subject_folder_strip()
        self._refresh_filter_button()

    def _subject_folder_strip(self) -> ft.Control:
        """Build the tappable subject folders shown above the task list."""
        folders: dict[str, ft.Button] = {}

        def folder_button(subject: Subject | None) -> ft.Button:
            subject_id = subject.id if subject else ""
            task_count = sum(
                task.subject_id == subject_id
                for task in self.task_cache
            ) if subject else len(self.task_cache)
            selected = self._task_filter_values["subject_id"] == subject_id
            title = subject.title if subject else "All tasks"
            button = ft.Button(
                content=f"{title} ({task_count})",
                icon=ft.Icons.FOLDER_OPEN if selected else ft.Icons.FOLDER,
                color=(
                    colors_for(self.dark_mode).primary
                    if selected
                    else self._secondary_text_color()
                ),
                icon_color=(
                    colors_for(self.dark_mode).primary
                    if selected
                    else self._secondary_text_color()
                ),
                bgcolor=(
                    self._accent_surface_color()
                    if selected
                    else self._raised_surface_color()
                ),
                tooltip=f"Show tasks for {title}",
                on_click=lambda _=None, value=subject_id: self._set_task_filter(
                    "subject_id", value
                ),
            )
            folders[subject_id] = button
            return button

        strip = ft.Container(
            content=ft.Row(
                controls=[
                    folder_button(None),
                    *(folder_button(subject) for subject in self.subject_cache),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=8,
            ),
            padding=ft.Padding(0, 2, 0, 4),
        )
        self._active_subject_folder_buttons = folders
        return strip

    def _refresh_subject_folder_strip(self) -> None:
        for subject_id, button in getattr(
            self, "_active_subject_folder_buttons", {}
        ).items():
            selected = self._task_filter_values["subject_id"] == subject_id
            button.icon = ft.Icons.FOLDER_OPEN if selected else ft.Icons.FOLDER
            button.color = (
                colors_for(self.dark_mode).primary
                if selected
                else self._secondary_text_color()
            )
            button.icon_color = button.color
            button.bgcolor = (
                self._accent_surface_color()
                if selected
                else self._raised_surface_color()
            )

    def _refresh_filter_button(self) -> None:
        button = getattr(self, "_active_filter_button", None)
        if button is None:
            return
        has_active_filters = any(
            self._task_filter_values[key]
            for key in ("subject_id", "status", "priority", "category")
        ) or self._task_filter_values["ordering"] != "deadline_asc"
        button.selected = self._filters_expanded or has_active_filters
        button.icon_color = (
            colors_for(self.dark_mode).primary
            if button.selected
            else self._secondary_text_color()
        )
        self.page.update()

    def _set_task_filter(self, key: str, value: str) -> None:
        self._task_filter_values[key] = value
        labels = {
            "subject_id": "Subject",
            "status": "Status",
            "priority": "Priority",
            "category": "Category",
            "ordering": "Sort by",
        }
        for control in getattr(self, "_active_filter_controls", []):
            if control.label == labels[key]:
                control.value = value
        self._apply_task_filters()

    def _toggle_task_filters(self, expanded: bool) -> None:
        self._filters_expanded = expanded
        panel = getattr(self, "_active_filter_panel", None)
        if panel is not None:
            panel.visible = expanded
        self._refresh_filter_button()

    def _reset_filters(self) -> None:
        self._task_filter_values.update(
            subject_id="",
            status="",
            priority="",
            category="",
            ordering="deadline_asc",
        )
        for control in getattr(self, "_active_filter_controls", []):
            control.value = self._task_filter_values[
                "ordering" if control.label == "Sort by" else {
                    "Subject": "subject_id",
                    "Status": "status",
                    "Priority": "priority",
                    "Category": "category",
                }[control.label]
            ]
        self._apply_task_filters()

    def _task_tile(self, task: Task, compact: bool = False) -> ft.Control:
        subject = next(
            (subject for subject in self.subject_cache if subject.id == task.subject_id),
            None,
        )
        deadline = (
            task.deadline.astimezone().strftime("%b %d, %Y")
            if task.deadline
            else "No deadline"
        )
        metadata = " · ".join(
            value
            for value in [
                subject.title if subject else "",
                deadline,
                f"{task.priority.title()} priority",
                task.category,
                ", ".join(task.tags),
            ]
            if value
        )
        if compact:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(task.title, weight=ft.FontWeight.BOLD),
                        ft.Text(metadata, size=12),
                    ],
                    spacing=3,
                ),
                padding=12,
                bgcolor=self._surface_color(),
                border_radius=10,
            )
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Checkbox(
                        value=task.status == "completed",
                        on_change=lambda event, item=task: self.page.run_task(
                            self._toggle_task, item, bool(event.control.value)
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(task.title, weight=ft.FontWeight.BOLD),
                            ft.Text(metadata, size=12, selectable=True),
                            ft.Text(task.status.replace("_", " ").title(), size=12),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.EDIT,
                        tooltip="Edit task",
                        on_click=lambda _, item=task: self._show_task_dialog(item),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        tooltip="Delete task",
                        on_click=lambda _, item=task: self._confirm_delete_task(item),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=8,
            bgcolor=self._surface_color(),
            border_radius=10,
        )

    async def _toggle_task(self, task: Task, checked: bool) -> None:
        try:
            await self.tasks.update_task(
                task.id,
                {"status": "completed" if checked else "pending"},
            )
        except (FirestoreError, DocumentNotFoundError, ModelValidationError, ValueError) as error:
            await self.show(self.route, notice=f"Could not update task: {error}")
            return
        await self.show(self.route, notice="Task status updated.", refresh=True)

    def _show_task_dialog(self, task: Task | None = None) -> None:
        return_route = self.route
        title = ft.TextField(label="Task title", value=task.title if task else "")
        description = ft.TextField(
            label="Description",
            value=task.description if task else "",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        selected_deadline: date | None = (
            task.deadline.astimezone().date() if task and task.deadline else None
        )
        deadline = ft.TextField(
            label="Deadline (optional)",
            value=(
                selected_deadline.strftime("%b %d, %Y")
                if selected_deadline
                else ""
            ),
            read_only=True,
            on_click=lambda _=None: self.page.show_dialog(deadline_picker),
            expand=True,
        )

        def update_deadline(event: Any) -> None:
            nonlocal selected_deadline
            picked = event.control.value
            if isinstance(picked, datetime):
                picked = picked.date()
            if isinstance(picked, date):
                selected_deadline = picked
                deadline.value = picked.strftime("%b %d, %Y")
                clear_deadline_button.visible = True
                self.page.update()

        deadline_picker = ft.DatePicker(
            value=selected_deadline,
            modal=True,
            first_date=date(1900, 1, 1),
            last_date=date(2200, 12, 31),
            help_text="Select task deadline",
            confirm_text="Select",
            cancel_text="Cancel",
            on_change=update_deadline,
        )

        def clear_deadline(_: Any = None) -> None:
            nonlocal selected_deadline
            selected_deadline = None
            deadline.value = ""
            clear_deadline_button.visible = False
            self.page.update()

        clear_deadline_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            tooltip="Clear deadline",
            visible=selected_deadline is not None,
            on_click=clear_deadline,
        )
        subject = ft.Dropdown(
            label="Subject (optional)",
            value=task.subject_id if task and task.subject_id else "",
            options=[
                ft.DropdownOption(key="", text="No subject"),
                *[
                    ft.DropdownOption(key=item.id, text=item.title)
                    for item in self.subject_cache
                ],
            ],
        )
        priority = ft.Dropdown(
            label="Priority",
            value=task.priority if task else "medium",
            options=[
                ft.DropdownOption(key=value, text=value.title())
                for value in self._PRIORITIES
            ],
        )
        category = ft.TextField(label="Category", value=task.category if task else "general")
        status = ft.Dropdown(
            label="Status",
            value=task.status if task else "pending",
            options=[
                ft.DropdownOption(key=value, text=value.replace("_", " ").title())
                for value in self._STATUSES
            ],
        )
        tags = ft.TextField(
            label="Tags (comma-separated)",
            value=", ".join(task.tags) if task else "",
        )
        error = ft.Text(color=self._error_text_color(), visible=False)

        async def save(_: Any) -> None:
            if not title.value or not title.value.strip():
                error.value = "Enter a task title."
                error.visible = True
                self.page.update()
                return
            try:
                due = self._deadline_for_date(selected_deadline)
                changes = {
                    "title": title.value.strip(),
                    "description": description.value or "",
                    "deadline": due,
                    "subject_id": subject.value or None,
                    "priority": priority.value or "medium",
                    "category": (category.value or "general").strip(),
                    "status": status.value or "pending",
                    "tags": [tag.strip() for tag in (tags.value or "").split(",") if tag.strip()],
                }
                if task:
                    await self.tasks.update_task(task.id, changes)
                else:
                    await self.tasks.create_task(**changes)
            except (
                FirestoreError,
                DocumentNotFoundError,
                ModelValidationError,
                ValueError,
            ) as save_error:
                error.value = str(save_error)
                error.visible = True
                self.page.update()
                return
            self.page.pop_dialog()
            await self.show(return_route, notice="Task saved.", refresh=True)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit task" if task else "Add task"),
            content=ft.Column(
                controls=[
                    title,
                    description,
                    ft.Row(
                        controls=[
                            deadline,
                            ft.IconButton(
                                icon=ft.Icons.CALENDAR_MONTH,
                                tooltip="Choose deadline",
                                on_click=lambda _=None: self.page.show_dialog(
                                    deadline_picker
                                ),
                            ),
                            clear_deadline_button,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    subject,
                    priority,
                    category,
                    status,
                    tags,
                    error,
                ],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self.page.pop_dialog()),
                ft.Button(content="Save", on_click=save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            scrollable=True,
            inset_padding=10,
        )
        self.page.show_dialog(dialog)

    @staticmethod
    def _deadline_for_date(selected_day: date | None) -> datetime | None:
        if selected_day is None:
            return None
        return datetime.combine(selected_day, time(23, 59)).astimezone()

    def _show_subject_dialog(self) -> None:
        title = ft.TextField(label="Subject title")
        color = ft.TextField(label="Color (hex)", value="#2196F3")
        description = ft.TextField(label="Description", multiline=True, min_lines=2)
        error = ft.Text(color=self._error_text_color(), visible=False)

        async def save(_: Any) -> None:
            try:
                await self.subjects.create_subject(
                    title.value or "",
                    color=color.value or "#2196F3",
                    description=description.value or "",
                )
            except (FirestoreError, ModelValidationError, ValueError) as save_error:
                error.value = str(save_error)
                error.visible = True
                self.page.update()
                return
            self.page.pop_dialog()
            await self.show("tasks", notice="Subject created.", refresh=True)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Add subject"),
                content=ft.Column(
                    controls=[title, color, description, error], tight=True
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(content="Save", on_click=save),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def _confirm_delete_task(self, task: Task) -> None:
        async def delete(_: Any) -> None:
            try:
                await self.tasks.delete_task(task.id)
            except (FirestoreError, DocumentNotFoundError, ValueError) as error:
                self.page.pop_dialog()
                await self.show("tasks", notice=f"Could not delete task: {error}")
                return
            self.page.pop_dialog()
            await self.show("tasks", notice="Task deleted.", refresh=True)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete task?"),
                content=ft.Text(f"Delete “{task.title}”? This cannot be undone."),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda _: self.page.pop_dialog()),
                    ft.Button(content="Delete", on_click=delete),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def _calendar_screen(self) -> ft.Control:
        palette = colors_for(self.dark_mode)
        today = date.today()
        dates_with_tasks = {
            task.deadline.astimezone().date()
            for task in self.task_cache
            if task.deadline is not None
        }
        cells = month_grid(self.displayed_month.year, self.displayed_month.month)
        weeks: list[ft.Control] = []
        weeks.append(
            ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(
                            day,
                            weight=ft.FontWeight.BOLD,
                            color=palette.secondary_text,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        alignment=ft.Alignment.CENTER,
                        expand=True,
                    )
                    for day in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                ],
                spacing=0,
                expand=True,
            )
        )
        for start in range(0, len(cells), 7):
            day_cells: list[ft.Control] = []
            for value in cells[start : start + 7]:
                if value is None:
                    day_cells.append(ft.Container(expand=True, height=52))
                    continue
                day_cells.append(
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    str(value.day),
                                    color=(
                                        palette.on_primary
                                        if value == self.selected_day
                                        else palette.text
                                    ),
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            width=5,
                                            height=5,
                                            bgcolor=palette.accent,
                                            border_radius=5,
                                        )
                                        if value in dates_with_tasks
                                        else ft.Container(width=5, height=5)
                                    ],
                                    alignment=ft.MainAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=2,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        alignment=ft.Alignment.CENTER,
                        expand=True,
                        height=52,
                        bgcolor=(
                            palette.primary
                            if value == self.selected_day
                            else None
                        ),
                        border=(
                            ft.Border.all(1, palette.accent)
                            if value == today
                            else None
                        ),
                        border_radius=10,
                        on_click=lambda _, selected=value: self._select_calendar_day(
                            selected
                        ),
                    )
                )
            weeks.append(
                ft.Row(
                    controls=day_cells,
                    spacing=0,
                    expand=True,
                )
            )
        day_tasks = tasks_for_date(self.task_cache, self.selected_day)
        return ft.ListView(
            controls=[
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_LEFT,
                            tooltip="Previous month",
                            on_click=lambda _: self._change_month(-1),
                        ),
                        ft.Text(
                            f"{month_name[self.displayed_month.month]} "
                            f"{self.displayed_month.year}",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            expand=True,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHEVRON_RIGHT,
                            tooltip="Next month",
                            on_click=lambda _: self._change_month(1),
                        ),
                        ft.TextButton(
                            "Today",
                            on_click=lambda _: self._go_to_today(),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Column(controls=weeks, spacing=2, expand=True),
                ft.Divider(color=palette.border),
                ft.Text(
                    f"Tasks for {self.selected_day.strftime('%B %d, %Y')}",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                ),
                *(
                    [self._task_tile(task) for task in day_tasks]
                    if day_tasks
                    else [ft.Text("No tasks scheduled for this date.")]
                ),
                ft.Text(
                    "Tasks without a deadline are available in the Tasks list and "
                    "do not appear on calendar dates.",
                    size=12,
                    color=palette.secondary_text,
                ),
            ],
            spacing=8,
            expand=True,
        )

    def _select_calendar_day(self, selected: date) -> None:
        self.selected_day = selected
        self.page.run_task(self.show, "calendar")

    def _change_month(self, difference: int) -> None:
        month_index = self.displayed_month.month - 1 + difference
        year = self.displayed_month.year + month_index // 12
        month = month_index % 12 + 1
        self.displayed_month = date(year, month, 1)
        _, number_of_days = monthrange(year, month)
        self.selected_day = date(
            year, month, min(self.selected_day.day, number_of_days)
        )
        self.page.run_task(self.show, "calendar")

    def _go_to_today(self) -> None:
        self.selected_day = date.today()
        self.displayed_month = self.selected_day.replace(day=1)
        self.page.run_task(self.show, "calendar")

    def _settings_screen(self) -> ft.Control:
        dark_mode = ft.Switch(
            label="Dark appearance",
            value=self.dark_mode,
            on_change=self._set_dark_mode,
        )
        return ft.ListView(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Appearance",
                                size=18,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                "Choose the color theme used throughout the app.",
                                size=13,
                                color=self._secondary_text_color(),
                            ),
                            dark_mode,
                        ],
                        spacing=6,
                    ),
                    padding=14,
                    bgcolor=self._surface_color(),
                    border_radius=12,
                ),
                ft.Divider(),
                ft.Text("Study assistance", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("AI study assistance"),
                            ft.Text(
                                "Task recommendations and the study chatbot are "
                                "available on the Home dashboard.",
                                size=12,
                                color=self._secondary_text_color(),
                            ),
                            ft.TextButton(
                                "Open Home",
                                icon=ft.Icons.HOME,
                                on_click=lambda _: self.page.run_task(
                                    self.show, "home"
                                ),
                            ),
                        ],
                        spacing=3,
                    ),
                    padding=14,
                    bgcolor=self._surface_color(),
                    border_radius=12,
                ),
                ft.OutlinedButton(
                    content="Profile and account",
                    icon=ft.Icons.PERSON,
                    on_click=lambda _: self.page.run_task(self.show, "profile"),
                ),
            ],
            spacing=10,
            expand=True,
        )

    def _set_dark_mode(self, event: Any) -> None:
        self.dark_mode = bool(event.control.value)
        apply_theme(self.page, self.dark_mode)
        notice = ""
        try:
            save_dark_mode(self.dark_mode)
        except OSError as error:
            logger.warning("Could not persist appearance preference: %s", error)
            notice = "Appearance changed, but could not be saved for next time."
        if self.auth.session is not None:
            self._render(self.auth.session, notice=notice)
        else:
            self.page.update()

    def _profile_screen(self, session: AuthSession) -> ft.Control:
        async def logout(_: Any) -> None:
            self._load_request_id += 1
            self.auth.logout()
            self._invalidate_ai_requests()
            self._clear_account_data()
            self.on_unauthenticated()

        return ft.ListView(
            controls=[
                ft.Icon(ft.Icons.ACCOUNT_CIRCLE, size=72),
                ft.Text(session.email or "Email not available", size=20),
                ft.Text("Firebase user ID", weight=ft.FontWeight.BOLD),
                ft.Text(session.uid, selectable=True),
                ft.Divider(),
                ft.Text(
                    "Your profile is linked to your authenticated Firebase account."
                ),
                ft.Button(
                    content="Log out",
                    icon=ft.Icons.LOGOUT,
                    on_click=logout,
                ),
            ],
            spacing=12,
            expand=True,
        )
