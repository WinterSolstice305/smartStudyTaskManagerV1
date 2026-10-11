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
        restored = await auth.restore_session()
        if restored is None:
            show_login()
            return
        logger.info("Application startup: restored saved Firebase session.")
        show_home()

    page.run_task(restore_or_show_login)


if __name__ == "__main__":
    ft.run(main)
