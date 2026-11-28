"""Shared, immutable light/dark design tokens. No process-global theme state."""
from __future__ import annotations

LIGHT = {
    "bg": "#F7F7FF", "card": "#FFFFFF", "surface": "#F0F1FE",
    "ink": "#16142B", "muted": "#5C5F82", "faint": "#8A8EB4",
    "line": "#E4E6FB", "track": "#E9EAF8",
    "accent": "#7C3AED", "accent-soft": "#EFE9FF", "accent-text": "#6D28D9",
    "green": "#22C55E", "blue": "#3B82F6", "amber": "#F59E0B", "coral": "#EF4444",
    "green-bg": "#DCFCE7", "green-text": "#15803D",
    "blue-bg": "#DBEAFE", "blue-text": "#1D4ED8",
    "amber-bg": "#FEF3C7", "amber-text": "#B45309",
    "coral-bg": "#FEE2E2", "coral-text": "#DC2626",
    "peer": "#14B8A6", "benchmark": "#D97706", "grid": "#E4E6FB",
    "shadow": "0 3px 16px rgba(124, 58, 237, 0.10)",
}
DARK = {
    "bg": "#12101F", "card": "#1A1730", "surface": "#252140",
    "ink": "#F4F3FF", "muted": "#A9A6D0", "faint": "#8B87B8",
    "line": "#322D55", "track": "#2C2750",
    "accent": "#A78BFA", "accent-soft": "#2E2566", "accent-text": "#C4B5FD",
    "green": "#22C55E", "blue": "#60A5FA", "amber": "#FBBF24", "coral": "#F87171",
    "green-bg": "#143325", "green-text": "#86EFAC",
    "blue-bg": "#172554", "blue-text": "#93C5FD",
    "amber-bg": "#3B2F0B", "amber-text": "#FDE68A",
    "coral-bg": "#451A1A", "coral-text": "#FCA5A5",
    "peer": "#2DD4BF", "benchmark": "#FBBF24", "grid": "#2A2650",
    "shadow": "0 4px 20px rgba(0, 0, 0, 0.35)",
}


def palette(mode: str = "light") -> dict[str, str]:
    return dict(DARK if mode == "dark" else LIGHT)
