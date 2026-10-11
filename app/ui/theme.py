import json
import logging
from dataclasses import dataclass
from pathlib import Path

import flet as ft


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThemeColors:
    background: str
    surface: str
    accent_surface: str
    elevated_surface: str
    primary: str
    accent: str
    on_primary: str
    text: str
    secondary_text: str
    border: str
    error: str


LIGHT = ThemeColors(
    background="#FFFFFF",
    surface="#F7F9FC",
    accent_surface="#EFF6FF",
    elevated_surface="#FFFFFF",
    primary="#2563EB",
    accent="#16A34A",
    on_primary="#FFFFFF",
    text="#172033",
    secondary_text="#64748B",
    border="#E2E8F0",
    error="#B91C1C",
)

DARK = ThemeColors(
    background="#0A0A0A",
    surface="#141414",
    accent_surface="#1B2D1F",
    elevated_surface="#1D1D1D",
    primary="#22C55E",
    accent="#22C55E",
    on_primary="#0A0A0A",
    text="#F5F5F5",
    secondary_text="#A3A3A3",
    border="#303030",
    error="#F87171",
)


def colors_for(dark_mode: bool) -> ThemeColors:
    return DARK if dark_mode else LIGHT


def apply_theme(page: ft.Page, dark_mode: bool) -> None:
    palette = colors_for(dark_mode)
    page.theme = ft.Theme(color_scheme_seed=LIGHT.primary, use_material3=True)
    page.dark_theme = ft.Theme(color_scheme_seed=DARK.primary, use_material3=True)
    page.theme_mode = ft.ThemeMode.DARK if dark_mode else ft.ThemeMode.LIGHT
    page.bgcolor = palette.background


def _preferences_path() -> Path:
    return Path.home() / ".smart-study-task-manager" / "preferences.json"


def load_dark_mode() -> bool:
    try:
        with _preferences_path().open(encoding="utf-8") as preferences_file:
            settings = json.load(preferences_file)
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        logger.warning("Could not load saved appearance preference: %s", error)
        return False
    if not isinstance(settings, dict):
        logger.warning("Saved appearance preference has an invalid format.")
        return False
    return settings.get("dark_mode") is True


def save_dark_mode(dark_mode: bool) -> None:
    path = _preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as preferences_file:
        json.dump({"dark_mode": dark_mode}, preferences_file)
    temporary_path.replace(path)