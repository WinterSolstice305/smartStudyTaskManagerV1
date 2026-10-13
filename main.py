import asyncio
import logging
import time

import flet as ft

from app.config import FIREBASE_API_KEY, FIREBASE_PROJECT_ID
from app.services.firebase_auth import FirebaseAuthService
from app.ui import login, register
from app.ui.workspace import StudyWorkspace


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(page: ft.Page) -> None:
    startup_started = time.perf_counter()
    logger.info("Application startup: Flet page is ready.")
    page.title = "Smart Study Task Manager"
    page.theme_mode = ft.ThemeMode.LIGHT
    auth = FirebaseAuthService(FIREBASE_API_KEY)
    logger.info("Application startup: authentication service initialized.")
    workspace = StudyWorkspace(
        page,
        auth,
        FIREBASE_PROJECT_ID,
        on_unauthenticated=lambda: show_login(),
    )
    auth.set_diagnostic_callback(workspace.record_startup_event)
    workspace.record_startup_event(
        "application startup",
        "success",
        "Flet page, authentication service, and workspace services initialized.",
    )
    logger.info("Application startup: workspace services initialized.")

    def show_login() -> None:
        login.show(page, auth, show_home, show_register)

    def show_register() -> None:
        register.show(page, auth, show_home, show_login)

    def show_home() -> None:
        if auth.session is None:
            show_login()
            logger.info(
                "Application startup: login screen built in %.2f seconds.",
                time.perf_counter() - startup_started,
            )
            return
        page.run_task(workspace.show, "home")

    async def restore_or_show_login() -> None:
        workspace.record_startup_event(
            "startup session restoration", "started", "Beginning persisted-session restoration."
        )
        try:
            restored = await asyncio.wait_for(auth.restore_session(), timeout=20)
        except asyncio.TimeoutError as error:
            workspace.record_startup_event(
                "startup session restoration",
                "error",
                f"{type(error).__name__}: Firebase session restoration exceeded 20 seconds.",
            )
            show_login()
            return
        except Exception as error:
            workspace.record_startup_event(
                "startup session restoration",
                "error",
                f"{type(error).__name__}: Could not restore the saved session.",
            )
            show_login()
            return
        if restored is None:
            workspace.record_startup_event(
                "startup session restoration",
                "warning",
                "No authenticated session was restored; showing the sign-in screen.",
            )
            show_login()
            return
        workspace.record_startup_event(
            "startup session restoration", "success", "Authenticated session is ready."
        )
        logger.info("Application startup: restored saved Firebase session.")
        show_home()

    page.run_task(restore_or_show_login)


if __name__ == "__main__":
    ft.run(main)
