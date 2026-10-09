from collections.abc import Callable

import flet as ft

from app.services.firebase_auth import FirebaseAuthError, FirebaseAuthService


def show(
    page: ft.Page,
    auth: FirebaseAuthService,
    on_authenticated: Callable[[], None],
    on_login: Callable[[], None],
) -> None:
    email = ft.TextField(label="Email", width=320)
    password = ft.TextField(label="Password", password=True, width=320)
    confirm_password = ft.TextField(
        label="Confirm password", password=True, width=320
    )
    error = ft.Text(visible=False)
    register_button = ft.Button(content="Register", width=320)

    async def submit() -> None:
        if not email.value or not email.value.strip():
            error.value = "Enter your email address."
        elif not password.value:
            error.value = "Enter a password."
        elif password.value != confirm_password.value:
            error.value = "Passwords do not match."
        else:
            error.visible = False
            register_button.disabled = True
            try:
                await auth.register(email.value.strip(), password.value)
            except FirebaseAuthError as auth_error:
                error.value = str(auth_error)
                error.visible = True
                register_button.disabled = False
                return
            on_authenticated()
            return

        error.visible = True

    register_button.on_click = submit
    page.clean()
    page.add(
        ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Create an account", size=24),
                    email,
                    password,
                    confirm_password,
                    error,
                    register_button,
                    ft.TextButton("Back to login", on_click=lambda _: on_login()),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )
    )
