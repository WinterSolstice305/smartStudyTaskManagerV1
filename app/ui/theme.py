import json
import logging
from dataclasses import dataclass
from pathlib import Path

import flet as ft

from app.services.storage import ensure_storage_root, storage_path


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


FONT_SCALES = {"small": 0.9, "default": 1.0, "large": 1.15}


def apply_theme(page: ft.Page, dark_mode: bool, font_size: str = "default") -> None:
    palette = colors_for(dark_mode)
    scale = FONT_SCALES.get(font_size, 1.0)
    text_theme = ft.TextTheme(
        body_large=ft.TextStyle(size=16 * scale, color=palette.text),
        body_medium=ft.TextStyle(size=14 * scale, color=palette.text),
        body_small=ft.TextStyle(size=12 * scale, color=palette.secondary_text),
        title_large=ft.TextStyle(size=22 * scale, color=palette.text),
        title_medium=ft.TextStyle(size=18 * scale, color=palette.text),
        title_small=ft.TextStyle(size=16 * scale, color=palette.text),
        headline_small=ft.TextStyle(size=24 * scale, color=palette.text),
    )
    color_scheme = ft.ColorScheme(
        primary=palette.primary,
        on_primary=palette.on_primary,
        primary_container=palette.accent_surface,
        on_primary_container=palette.text,
        secondary=palette.accent,
        on_secondary=palette.on_primary,
        surface=palette.background,
        on_surface=palette.text,
        on_surface_variant=palette.secondary_text,
        outline=palette.border,
        outline_variant=palette.border,
        error=palette.error,
        on_error=palette.on_primary,
    )
    page.theme = ft.Theme(
        color_scheme=color_scheme,
        use_material3=True,
        text_theme=text_theme,
        scaffold_bgcolor=palette.background,
        canvas_color=palette.background,
        card_bgcolor=palette.elevated_surface,
        divider_color=palette.border,
        hint_color=palette.secondary_text,
        unselected_control_color=palette.secondary_text,
        disabled_color=palette.secondary_text,
        icon_theme=ft.IconTheme(color=palette.text),
    )
    page.dark_theme = page.theme if dark_mode else ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=DARK.primary,
            on_primary=DARK.on_primary,
            primary_container=DARK.accent_surface,
            on_primary_container=DARK.text,
            secondary=DARK.accent,
            on_secondary=DARK.on_primary,
            surface=DARK.background,
            on_surface=DARK.text,
            on_surface_variant=DARK.secondary_text,
            outline=DARK.border,
            outline_variant=DARK.border,
            error=DARK.error,
            on_error=DARK.on_primary,
        ),
        use_material3=True,
        text_theme=ft.TextTheme(
            body_large=ft.TextStyle(size=16 * scale, color=DARK.text),
            body_medium=ft.TextStyle(size=14 * scale, color=DARK.text),
            body_small=ft.TextStyle(size=12 * scale, color=DARK.secondary_text),
            title_large=ft.TextStyle(size=22 * scale, color=DARK.text),
            title_medium=ft.TextStyle(size=18 * scale, color=DARK.text),
            title_small=ft.TextStyle(size=16 * scale, color=DARK.text),
            headline_small=ft.TextStyle(size=24 * scale, color=DARK.text),
        ),
        scaffold_bgcolor=DARK.background,
        canvas_color=DARK.background,
        card_bgcolor=DARK.elevated_surface,
        divider_color=DARK.border,
        hint_color=DARK.secondary_text,
        unselected_control_color=DARK.secondary_text,
        disabled_color=DARK.secondary_text,
        icon_theme=ft.IconTheme(color=DARK.text),
    )
    page.theme_mode = ft.ThemeMode.DARK if dark_mode else ft.ThemeMode.LIGHT
    page.bgcolor = palette.background


def _preferences_path() -> Path:
    return storage_path("preferences.json")


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


def load_font_size() -> str:
    try:
        with _preferences_path().open(encoding="utf-8") as preferences_file:
            settings = json.load(preferences_file)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return "default"
    value = settings.get("font_size") if isinstance(settings, dict) else None
    return value if value in FONT_SCALES else "default"


def save_dark_mode(dark_mode: bool) -> None:
    save_appearance(dark_mode, load_font_size())


def save_appearance(dark_mode: bool, font_size: str) -> None:
    if font_size not in FONT_SCALES:
        font_size = "default"
    path = _preferences_path()
    ensure_storage_root()
    temporary_path = path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as preferences_file:
        json.dump({"dark_mode": dark_mode, "font_size": font_size}, preferences_file)
    temporary_path.replace(path)
