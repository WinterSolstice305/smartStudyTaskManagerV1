from collections.abc import Callable

import flet as ft

from app.services.firebase_auth import AuthSession


def show(page: ft.Page, session: AuthSession, on_logout: Callable[[], None]) -> None:
    page.clean()
    page.add(
        ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Logged in", size=24),
                    ft.Text(f"Email: {session.email}"),
                    ft.Text(f"UID: {session.uid}", selectable=True),
                    ft.Button(content="Log out", on_click=lambda _: on_logout()),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )
    )
