from calendar import month_name
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
from app.services.task_service import TaskService
from app.ui.task_views import filter_tasks, month_grid, sort_tasks, tasks_for_date


class StudyWorkspace:
    _ROUTES = ["home", "tasks", "calendar", "settings"]
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
        self._recommendation_loading = False
        self._recommendation_request_id = 0
        self._recommendation_result: TaskRecommendationResult | None = None
        self._recommendation_error = ""
        self._chat_loading = False
        self._chat_request_id = 0
        self._chat_message = ""
        self._chat_response = ""
        self._chat_error = ""

    async def show(self, route: str | None = None, notice: str = "") -> None:
        if self.auth.session is None:
            self._invalidate_ai_requests()
            self._clear_account_data()
            self.on_unauthenticated()
            return
        if route in (*self._ROUTES, "profile"):
            self.route = route
        session = self.auth.session
        if session is None:
            self._invalidate_ai_requests()
            self._clear_account_data()
            self.on_unauthenticated()
            return
        self._invalidate_ai_requests()
        self._data_loading = True
        self._data_available = False
        self._clear_ai_state()
        if self._data_uid != session.uid:
            self._clear_account_data()
            self._data_uid = session.uid
        error_message = ""
        try:
            self.task_cache, self.subject_cache = await self._load_data(session)
            self._data_available = True
        except AuthenticationRequiredError:
            self.task_cache = []
            self.subject_cache = []
            self._data_uid = None
            self._data_loading = False
            self._data_available = False
            self._clear_ai_state()
            self.on_unauthenticated()
            return
        except FirestoreError as error:
            error_message = str(error)
            self.task_cache = []
            self.subject_cache = []
        except (ModelValidationError, ValueError) as error:
            error_message = f"Could not read saved study data: {error}"
            self.task_cache = []
            self.subject_cache = []
        self._data_loading = False
        self._render(session, notice=notice, error=error_message)

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

        tasks, subjects = await asyncio.gather(
            self.tasks.get_tasks(), self.subjects.get_subjects()
        )
        return tasks, subjects

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
        if error:
            status_controls.append(
                ft.Text(error, color=self._error_text_color(), selectable=True)
            )
        home_action = (
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.FloatingActionButton(
                            icon=ft.Icons.ADD,
                            tooltip="Add Task",
                            bgcolor=ft.Colors.BLUE_700,
                            foreground_color=ft.Colors.WHITE,
                            on_click=lambda _: self._show_task_dialog(),
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
                padding=ft.Padding(0, 0, 16, 8),
            )
            if self.route == "home"
            else None
        )
        self.page.clean()
        self.page.add(
            ft.Column(
                controls=[
                    ft.Container(header, padding=ft.Padding(16, 12, 8, 8)),
                    *status_controls,
                    ft.Container(content=body, expand=True, padding=ft.Padding(16, 4, 16, 12)),
                    *([home_action] if home_action is not None else []),
                    self._navigation_bar(),
                ],
                spacing=0,
                expand=True,
            )
        )

    def _surface_color(self) -> str:
        return ft.Colors.GREY_900 if self.dark_mode else ft.Colors.GREY_100

    def _raised_surface_color(self) -> str:
        return ft.Colors.GREY_800 if self.dark_mode else ft.Colors.WHITE

    def _accent_surface_color(self) -> str:
        return ft.Colors.BLUE_900 if self.dark_mode else ft.Colors.BLUE_50

    def _secondary_text_color(self) -> str:
        return ft.Colors.GREY_400 if self.dark_mode else ft.Colors.GREY_700

    def _error_text_color(self) -> str:
        return ft.Colors.RED_300 if self.dark_mode else ft.Colors.RED_700

    def _success_text_color(self) -> str:
        return ft.Colors.GREEN_300 if self.dark_mode else ft.Colors.GREEN_700

    def _navigation_bar(self) -> ft.NavigationBar:
        selected_index = (
            self._ROUTES.index(self.route) if self.route in self._ROUTES else 0
        )
        return ft.NavigationBar(
            selected_index=selected_index,
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
            on_change=lambda event: self.page.run_task(
                self.show, self._ROUTES[event.control.selected_index]
            ),
        )

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
        controls: list[ft.Control] = [
            ft.Text("AI task recommendations", size=18, weight=ft.FontWeight.BOLD)
        ]
        if self._recommendation_loading:
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
                    disabled=self._data_loading or not self._data_available,
                    on_click=lambda _: self.page.run_task(
                        self._request_recommendations
                    ),
                )
            )
        return ft.Column(controls=controls, spacing=8)

    def _chat_panel(self) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Text("Study planning assistant", size=18, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Ask about your current deadlines, workload, or what to study next."
            ),
        ]
        if not self._data_available:
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
        if self._chat_loading:
            controls.extend([ft.ProgressBar(), ft.Text("Thinking…")])
        elif self._chat_error:
            controls.append(ft.Text(self._chat_error, color=self._error_text_color()))
        elif self._chat_response:
            controls.append(ft.Text(self._chat_response, selectable=True))
        controls.extend(
            [
                ft.TextField(
                    label="Ask about your study workload",
                    value=self._chat_message,
                    multiline=True,
                    min_lines=2,
                    max_lines=4,
                    disabled=(
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
            result = await generate_task_recommendations(tasks, subjects)
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
            response = await chat_about_tasks(message, tasks, subjects)
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
        subject_filter = ft.Dropdown(
            label="Subject",
            value="",
            options=[
                ft.DropdownOption(key="", text="All subjects"),
                *[
                    ft.DropdownOption(key=subject.id, text=subject.title)
                    for subject in self.subject_cache
                ],
            ],
            on_select=lambda _: self._apply_task_filters(),
            expand=True,
        )
        status_filter = ft.Dropdown(
            label="Status",
            value="",
            options=[
                ft.DropdownOption(key="", text="All statuses"),
                *[
                    ft.DropdownOption(key=status, text=status.replace("_", " ").title())
                    for status in self._STATUSES
                ],
            ],
            on_select=lambda _: self._apply_task_filters(),
            expand=True,
        )
        priority_filter = ft.Dropdown(
            label="Priority",
            value="",
            options=[
                ft.DropdownOption(key="", text="All priorities"),
                *[
                    ft.DropdownOption(key=value, text=value.title())
                    for value in self._PRIORITIES
                ],
            ],
            on_select=lambda _: self._apply_task_filters(),
            expand=True,
        )
        category_values = sorted({task.category for task in self.task_cache})
        category_filter = ft.Dropdown(
            label="Category",
            value="",
            options=[
                ft.DropdownOption(key="", text="All categories"),
                *[
                    ft.DropdownOption(key=value, text=value)
                    for value in category_values
                ],
            ],
            on_select=lambda _: self._apply_task_filters(),
            expand=True,
        )
        sort_control = ft.Dropdown(
            label="Sort by",
            value="deadline_asc",
            options=[
                ft.DropdownOption(key=value, text=label)
                for label, value in self._SORTS.items()
            ],
            on_select=lambda _: self._apply_task_filters(),
            expand=True,
        )
        task_list = ft.Column(spacing=8)
        filters = [subject_filter, status_filter, priority_filter, category_filter]

        def update_list(update_page: bool = True) -> None:
            selected = filter_tasks(
                self.task_cache,
                subject_id=subject_filter.value or "",
                status=status_filter.value or "",
                priority=priority_filter.value or "",
                category=category_filter.value or "",
            )
            selected = sort_tasks(selected, sort_control.value or "deadline_asc")
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

    def _reset_filters(self) -> None:
        controls = getattr(self, "_active_filter_controls", [])
        for control in controls:
            control.value = "deadline_asc" if control.label == "Sort by" else ""
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
        await self.show(self.route, notice="Task status updated.")

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
        deadline = ft.TextField(
            label="Deadline (YYYY-MM-DD; optional)",
            value=(
                task.deadline.astimezone().date().isoformat()
                if task and task.deadline
                else ""
            ),
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
                due = self._parse_deadline(deadline.value or "")
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
            await self.show(return_route, notice="Task saved.")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit task" if task else "Add task"),
            content=ft.Column(
                controls=[
                    title,
                    description,
                    deadline,
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
        )
        self.page.show_dialog(dialog)

    @staticmethod
    def _parse_deadline(value: str) -> datetime | None:
        value = value.strip()
        if not value:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Enter a valid deadline in YYYY-MM-DD format.") from error
        return datetime.combine(parsed, time(23, 59)).astimezone()

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
            await self.show("tasks", notice="Subject created.")

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
            await self.show("tasks", notice="Task deleted.")

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
                    ft.Container(ft.Text(day, weight=ft.FontWeight.BOLD), width=40)
                    for day in ["S", "M", "T", "W", "T", "F", "S"]
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
        )
        for start in range(0, len(cells), 7):
            day_cells: list[ft.Control] = []
            for value in cells[start : start + 7]:
                if value is None:
                    day_cells.append(ft.Container(width=40, height=42))
                    continue
                label = str(value.day)
                if value in dates_with_tasks:
                    label = f"{label} •"
                day_cells.append(
                    ft.Container(
                        content=ft.TextButton(
                            label,
                            on_click=lambda _, selected=value: self._select_calendar_day(
                                selected
                            ),
                        ),
                        width=40,
                        height=42,
                        bgcolor=(
                            ft.Colors.BLUE_700
                            if self.dark_mode
                            else ft.Colors.BLUE_100
                        )
                        if value == self.selected_day
                        else None,
                        border_radius=8,
                    )
                )
            weeks.append(
                ft.Row(
                    controls=day_cells,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
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
                    ]
                ),
                *weeks,
                ft.Divider(),
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
                ft.Text("Notifications", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(
                                ft.Icons.NOTIFICATIONS_OUTLINED,
                                color=self._secondary_text_color(),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "Deadline reminders",
                                        weight=ft.FontWeight.W_500,
                                    ),
                                    ft.Text(
                                        "Notifications are not configured in this version.",
                                        size=12,
                                        color=self._secondary_text_color(),
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Text(
                                "Unavailable",
                                size=12,
                                color=self._secondary_text_color(),
                            ),
                        ]
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
        self.page.theme_mode = (
            ft.ThemeMode.DARK if self.dark_mode else ft.ThemeMode.LIGHT
        )
        if self.auth.session is not None:
            self._render(self.auth.session)
        else:
            self.page.update()

    def _profile_screen(self, session: AuthSession) -> ft.Control:
        async def logout(_: Any) -> None:
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
