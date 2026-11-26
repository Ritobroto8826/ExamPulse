"""Shared, immutable light/dark design tokens. No process-global theme state."""
from __future__ import annotations

LIGHT = {
    "bg": "#F5F6FA", "card": "#FFFFFF", "surface": "#F7F9FD",
    "ink": "#17243B", "muted": "#5F6F87", "faint": "#718099",
    "line": "#E3E8F1", "track": "#E9EDF5",
    "accent": "#5B4BD8", "accent-soft": "#EEEBFC", "accent-text": "#4D3CC2",
    "green": "#16866C", "blue": "#356DC8", "amber": "#BA770E", "coral": "#D95057",
    "green-bg": "#E8F5EF", "green-text": "#14694F",
    "blue-bg": "#EBF1FC", "blue-text": "#2856A3",
    "amber-bg": "#FFF4DF", "amber-text": "#8F5C09",
    "coral-bg": "#FCECEE", "coral-text": "#AF3543",
    "peer": "#167D95", "benchmark": "#B76B11", "grid": "#E9EDF4",
    "shadow": "0 3px 16px rgba(23, 36, 59, 0.035)",
}
DARK = {
    "bg": "#0B1220", "card": "#131F31", "surface": "#19283D",
    "ink": "#EDF2FC", "muted": "#A9B8CF", "faint": "#94A5BF",
    "line": "#2A3A52", "track": "#293951",
    "accent": "#AA9BFF", "accent-soft": "#302A4E", "accent-text": "#C2B6FF",
    "green": "#49C7A1", "blue": "#77AAFF", "amber": "#E9B457", "coral": "#FF8D96",
    "green-bg": "#173B34", "green-text": "#80DFC0",
    "blue-bg": "#1D3454", "blue-text": "#A1C5FF",
    "amber-bg": "#3D3220", "amber-text": "#F0C779",
    "coral-bg": "#422934", "coral-text": "#FFA6AE",
    "peer": "#50B4CB", "benchmark": "#E9B457", "grid": "#29384E",
    "shadow": "0 4px 20px rgba(0, 0, 0, 0.12)",
}


def palette(mode: str = "light") -> dict[str, str]:
    return dict(DARK if mode == "dark" else LIGHT)
