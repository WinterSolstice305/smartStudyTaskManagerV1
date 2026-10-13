"""Load and persist the user's local Groq direct-mode configuration."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.services.storage import ensure_storage_root, storage_path


logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_FILENAME = "groq-config.json"

load_dotenv(_PROJECT_ROOT / ".env", override=False)


def groq_api_key_configured() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "").strip() or _stored_api_key())


def groq_api_key_source() -> str:
    if os.environ.get("GROQ_API_KEY", "").strip():
        return "Groq key loaded from .env or the process environment."
    if _stored_api_key():
        return "Groq key saved in this app's private storage."
    return "No Groq API key is configured."


def get_groq_api_key() -> str:
    """Prefer an environment key, then the app-private user configuration."""
    environment_key = os.environ.get("GROQ_API_KEY", "").strip()
    return environment_key or _stored_api_key()


def save_groq_api_key(api_key: str) -> None:
    """Save a user's key to app-private storage without logging its contents."""
    normalized_key = api_key.strip()
    if not normalized_key:
        raise ValueError("Enter a Groq API key before saving.")
    if len(normalized_key) > 512 or any(character.isspace() for character in normalized_key):
        raise ValueError("The Groq API key format is invalid.")

    path = storage_path(_CONFIG_FILENAME)
    ensure_storage_root()
    temporary_path = path.with_suffix(".tmp")
    try:
        temporary_path.write_text(
            json.dumps({"groq_api_key": normalized_key}),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError:
        logger.exception("Could not save the Groq key in app-private storage.")
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove a temporary Groq configuration file.")
        raise


def clear_saved_groq_api_key() -> None:
    """Remove the app-private key; environment configuration remains unchanged."""
    path = storage_path(_CONFIG_FILENAME)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove the saved Groq key.")
        raise


def _stored_api_key() -> str:
    path = storage_path(_CONFIG_FILENAME)
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read the saved Groq configuration.")
        return ""
    if not isinstance(value, dict):
        logger.warning("Saved Groq configuration has an invalid format.")
        return ""
    api_key = value.get("groq_api_key")
    return api_key.strip() if isinstance(api_key, str) else ""
