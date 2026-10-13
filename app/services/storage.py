"""Platform-safe application-private storage paths."""

import logging
import os
import sys
import tempfile
from pathlib import Path


logger = logging.getLogger(__name__)

_APP_DIRECTORY = ".smart-study-task-manager"
_FLET_DATA_ENV = "FLET_APP_STORAGE_DATA"
_FLET_SUPPORT_ENV = "FLET_APP_STORAGE_SUPPORT"


class StoragePathError(OSError):
    """Raised when the app-private storage directory cannot be used."""


def storage_root() -> Path:
    """Return the stable, app-private root for persistent local data.

    Flet sets ``FLET_APP_STORAGE_DATA`` to an Android application-private
    directory. Desktop builds retain the existing home-directory location so
    existing local data remains compatible.
    """
    flet_data = os.environ.get(_FLET_DATA_ENV, "").strip()
    flet_support = os.environ.get(_FLET_SUPPORT_ENV, "").strip()
    if flet_data:
        root = Path(flet_data) / _APP_DIRECTORY
        logger.info("Application storage root resolved from %s: %s", _FLET_DATA_ENV, root)
        return root
    if flet_support:
        root = Path(flet_support) / "data" / _APP_DIRECTORY
        logger.info("Application storage root resolved from %s: %s", _FLET_SUPPORT_ENV, root)
        return root

    home = Path.home()
    if sys.platform == "android" or str(home) in {"/", "/data"}:
        # This is a last-resort compatibility path. Flet Android builds should
        # always provide FLET_APP_STORAGE_DATA; never use /data directly.
        root = Path(tempfile.gettempdir()) / _APP_DIRECTORY
        logger.warning(
            "Flet app storage environment is unavailable; using temporary app-private path: %s",
            root,
        )
        return root

    root = home / _APP_DIRECTORY
    logger.info("Application storage root resolved from desktop home: %s", root)
    return root


def ensure_storage_root() -> Path:
    root = storage_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except PermissionError as error:
        logger.error("Application storage permission denied for %s", root)
        raise StoragePathError(
            "The app-private storage directory is not writable. "
            "Check the Flet storage configuration."
        ) from error
    except OSError as error:
        logger.error("Application storage could not be created at %s: %s", root, error)
        raise StoragePathError(
            "The app-private storage directory could not be created."
        ) from error
    return root


def storage_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename:
        raise ValueError("Storage filenames must be a single filename.")
    return storage_root() / filename
