import flet as ft

from app.config import FIREBASE_API_KEY, FIREBASE_PROJECT_ID
from app.services.firebase_auth import FirebaseAuthService
from app.ui import login, register
from app.ui.workspace import StudyWorkspace


def main(page: ft.Page) -> None:
    page.title = "Smart Study Task Manager"
    page.theme_mode = ft.ThemeMode.LIGHT
    auth = FirebaseAuthService(FIREBASE_API_KEY)
    workspace = StudyWorkspace(
        page,
        auth,
        FIREBASE_PROJECT_ID,
        on_unauthenticated=lambda: show_login(),
    )

    def show_login() -> None:
        login.show(page, auth, show_home, show_register)

    def show_register() -> None:
        register.show(page, auth, show_home, show_login)

    def show_home() -> None:
        if auth.session is None:
            show_login()
            return
        page.run_task(workspace.show, "home")

    show_login()


if __name__ == "__main__":
    ft.run(main)
