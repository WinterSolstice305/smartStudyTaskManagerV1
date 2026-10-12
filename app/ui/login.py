from collections.abc import Callable
import logging

import flet as ft

from app.services.firebase_auth import FirebaseAuthError, FirebaseAuthService


logger = logging.getLogger(__name__)


def show(
    page: ft.Page,
    auth: FirebaseAuthService,
    on_authenticated: Callable[[], None],
    on_register: Callable[[], None],
) -> None:
    email = ft.TextField(label="Email", width=320)
    password = ft.TextField(label="Password", password=True, width=320)
    error = ft.Text(visible=False)
    login_button = ft.Button(content="Log in", width=320)
    guest_button = ft.Button(content="Continue as guest", width=320)

    async def submit() -> None:
        if not email.value or not email.value.strip() or not password.value:
            error.value = "Enter your email and password."
            error.visible = True
            return

        login_button.disabled = True
        error.visible = False
        try:
            await auth.login(email.value.strip(), password.value)
        except FirebaseAuthError as auth_error:
            error.value = str(auth_error)
            error.visible = True
            login_button.disabled = False
            return

        on_authenticated()

    async def submit_guest() -> None:
        login_button.disabled = True
        guest_button.disabled = True
        error.visible = False
        try:
            await auth.login_as_guest()
        except FirebaseAuthError as auth_error:
            error.value = str(auth_error)
            error.visible = True
            login_button.disabled = False
            guest_button.disabled = False
            return
        on_authenticated()

    def confirm_guest(_: object) -> None:
        async def continue_as_guest(_: object) -> None:
            page.pop_dialog()
            await submit_guest()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Continue as guest?"),
                content=ft.Text(
                    "Guest data is stored locally and will be permanently lost "
                    "when any user logs in. Continue?"
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button(content="Continue", on_click=continue_as_guest),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    login_button.on_click = submit
    guest_button.on_click = confirm_guest
    page.clean()
    page.add(
        ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Smart Study Task Manager", size=24),
                    ft.Text("Log in"),
                    email,
                    password,
                    error,
                    login_button,
                    guest_button,
                    ft.TextButton(
                        "Create an account", on_click=lambda _: on_register()
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )
    )
    logger.info("Login screen added to the Flet page.")
