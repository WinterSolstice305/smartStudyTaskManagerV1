import re


SUBJECT_COLOR_PALETTE: tuple[tuple[str, str], ...] = (
    (" ", "#2563EB"),
    (" ", "#DC2626"),
    (" ", "#059669"),
    (" ", "#D97706"),
    (" ", "#7C3AED"),
    (" ", "#DB2777"),
    (" ", "#0891B2"),
    (" ", "#4F46E5"),
)

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SUBJECT_COLOR_FALLBACK = SUBJECT_COLOR_PALETTE[0][1]


def valid_subject_color(value: str | None) -> bool:
    return isinstance(value, str) and bool(_HEX_COLOR.fullmatch(value.strip()))


def subject_color_or_fallback(value: str | None) -> str:
    return value.strip() if valid_subject_color(value) else SUBJECT_COLOR_FALLBACK


def foreground_for_subject_color(value: str) -> str:
    """Return readable text for a solid subject-color swatch."""
    color = subject_color_or_fallback(value).removeprefix("#")
    channels = [int(color[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92
        if channel <= 0.03928
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#172033" if luminance > 0.45 else "#FFFFFF"
