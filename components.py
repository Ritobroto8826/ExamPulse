"""HTML/CSS component renderers (KPI cards, rings, lists, bars, badges)."""
from __future__ import annotations

import html
from datetime import datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AVATAR_COLORS = ["#6C5CE7", "#0EA96D", "#F59E0B", "#EF4444", "#3B82F6", "#8B5CF6"]


def esc(value) -> str:
    return html.escape(str(value))


def initials_of(name: str) -> str:
    parts = str(name).split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return str(name)[:2].upper()


def avatar_color(name: str) -> str:
    return AVATAR_COLORS[sum(ord(c) for c in str(name)) % len(AVATAR_COLORS)]


def band(value: float, threshold: int) -> tuple[str, str, str]:
    """Return (color, label, pill-class) for a score vs. mastery threshold.

    Default threshold 70 reproduces the spec scale:
    Green >= 80, Blue 70-79, Amber 60-69, Coral < 60.
    """
    if value >= threshold + 10:
        return "#10B981", "Strong", "pill-green"
    if value >= threshold:
        return "#3B82F6", "On Track", "pill-blue"
    if value >= threshold - 10:
        return "#F59E0B", "Needs Focus", "pill-amber"
    return "#FF6B6B", "Critical", "pill-coral"


# ---------------------------------------------------------------------------
# Page / card headers
# ---------------------------------------------------------------------------

def page_head(title: str, subtitle: str = "") -> str:
    sub = f'<div class="page-sub">{esc(subtitle)}</div>' if subtitle else ""
    return (f'<div class="page-head"><div class="page-eyebrow">ACADEMIC INSIGHTS</div>'
            f'<div class="page-title">{esc(title)}</div>{sub}</div>')


def card_head(title: str, subtitle: str = "") -> str:
    sub = f'<div class="card-sub">{esc(subtitle)}</div>' if subtitle else ""
    return f'<div class="card-head"><div class="card-title">{esc(title)}</div>{sub}</div>'


# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

def _ring_svg(pct: float, color: str) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    return (
        '<div class="ring-wrap">'
        '<svg class="ring-svg" viewBox="0 0 36 36" aria-hidden="true">'
        '<circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--track)"'
        ' stroke-width="3.2"/>'
        f'<circle cx="18" cy="18" r="15.9155" fill="none" stroke="{color}"'
        ' stroke-width="3.2" stroke-linecap="round"'
        f' stroke-dasharray="{pct:.1f} {100 - pct:.1f}"'
        ' transform="rotate(-90 18 18)"/>'
        "</svg>"
        f'<div class="ring-center">{pct:.0f}%</div>'
        "</div>"
    )


def kpi_row(cards: list[dict]) -> str:
    """cards: {label, value?, delta?, delta_dir?} or {label, ring, ring_color, sub}."""
    parts = ['<div class="kpi-row">']
    for c in cards:
        if c.get("ring") is not None:
            color = "var(--green)" if c.get("ring_color") == "#10B981" else "var(--accent)"
            parts.append(
                '<div class="kpi-card ring-card">'
                + _ring_svg(c["ring"], color)
                + '<div class="ring-text">'
                + f'<div class="kpi-label">{esc(c["label"])}</div>'
                + f'<div class="ring-sub">{esc(c.get("sub", ""))}</div>'
                + "</div></div>"
            )
        else:
            delta_html = ""
            if c.get("delta"):
                direction = c.get("delta_dir", "flat")
                arrow = {"up": "▲", "down": "▼", "flat": "●"}.get(direction, "")
                delta_html = (
                    f'<div class="kpi-delta {direction}">{arrow} '
                    f'{esc(c["delta"])}</div>'
                )
            parts.append(
                '<div class="kpi-card">'
                + f'<div class="kpi-label">{esc(c["label"])}</div>'
                + f'<div class="kpi-value">{esc(c.get("value", ""))}</div>'
                + delta_html
                + "</div>"
            )
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Leaderboard / focus list
# ---------------------------------------------------------------------------

def leaderboard_html(rows: list[dict]) -> str:
    """rows: {rank, name, meta, badge?, badge_neg?, avatar?} or
    {rank, name, meta, pill, pill_class}."""
    if not rows:
        return '<div class="card-sub">Nothing to show yet.</div>'
    out = ['<div class="lb-list">']
    for r in rows:
        rank = esc(r.get("rank", ""))
        avatar = ""
        if r.get("avatar"):
            color = avatar_color(r["avatar"])
            avatar = (
                f'<div class="lb-avatar" style="background:{color}">'
                f'{esc(initials_of(r["avatar"]))}</div>'
            )
        right = ""
        if r.get("badge"):
            neg = " neg" if r.get("badge_neg") else ""
            right = f'<div class="lb-badge{neg}">{esc(r["badge"])}</div>'
        elif r.get("pill"):
            cls = r.get("pill_class", "pill-blue")
            right = f'<span class="pill {cls}">{esc(r["pill"])}</span>'
        out.append(
            '<div class="lb-row">'
            + f'<div class="lb-rank">{rank}</div>'
            + avatar
            + '<div class="lb-info">'
            + f'<div class="lb-name">{esc(r["name"])}</div>'
            + f'<div class="lb-meta">{esc(r.get("meta", ""))}</div>'
            + "</div>"
            + right
            + "</div>"
        )
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Horizontal progress bars
# ---------------------------------------------------------------------------

def progress_bars_html(items: list[tuple[str, float]], threshold: int,
                       show_legend: bool = True) -> str:
    """items: [(label, value)] sorted by the caller; color bands follow `threshold`."""
    if not items:
        return '<div class="card-sub">No data yet.</div>'
    out = []
    for label, value in items:
        value = float(value)
        color, _lab, _pill = band(value, threshold)
        out.append(
            '<div class="pb-row">'
            + '<div class="pb-head">'
            + f'<span class="pb-label">{esc(label)}</span>'
            + f'<span class="pb-val">{value:.0f}%</span>'
            + "</div>"
            + '<div class="pb-track">'
            + f'<div class="pb-fill {_pill}" style="width:{max(0, min(100, value)):.1f}%"></div>'
            + "</div></div>"
        )
    if show_legend:
        out.append(
            f'<div class="pb-legend">Green ≥ {threshold + 10} · '
            f"Blue {threshold}–{threshold + 9} · "
            f"Amber {threshold - 10}–{threshold - 1} · "
            f"Coral &lt; {threshold - 10} &nbsp;|&nbsp; sorted weakest first</div>"
        )
    return "".join(out)


# ---------------------------------------------------------------------------
# Schedule list
# ---------------------------------------------------------------------------

def schedule_html(items: list[dict], today: datetime | None = None) -> str:
    """items: {title, date (iso str), meta, notes?} — compact calendar list."""
    today = today or datetime.now()
    if not items:
        return '<div class="card-sub">No upcoming tests scheduled. 🎉</div>'
    out = ['<div class="sch-list">']
    for it in items[:7]:
        try:
            d = datetime.fromisoformat(str(it["date"])[:10])
        except ValueError:
            continue
        delta = (d.date() - today.date()).days
        if delta < 0:
            continue
        if delta == 0:
            when, soon = "Today", True
        elif delta == 1:
            when, soon = "Tomorrow", True
        elif delta <= 3:
            when, soon = f"in {delta} days", True
        else:
            when, soon = f"in {delta} days", False
        notes = it.get("notes")
        meta = it.get("meta", "")
        if notes:
            meta = f"{meta} · {notes}" if meta else str(notes)
        out.append(
            '<div class="sch-item">'
            + '<div class="sch-date">'
            + f'<span class="sch-day">{d.day:02d}</span>'
            + f'<span class="sch-mon">{d.strftime("%b").upper()}</span>'
            + "</div>"
            + '<div class="sch-body">'
            + f'<div class="sch-title">{esc(it["title"])}</div>'
            + f'<div class="sch-meta">{esc(meta)}</div>'
            + "</div>"
            + f'<span class="sch-in{" soon" if soon else ""}">{when}</span>'
            + "</div>"
        )
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Login / profile
# ---------------------------------------------------------------------------

def login_hero_html() -> str:
    return (
        '<div class="login-hero">'
        '<div class="logo-dot"><svg width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M3 16h4l3-9 4 13 3-9h4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
        "<h1>ExamPulse</h1>"
        "<p>Track exam scores · spot weak topics · improve faster.</p>"
        "</div>"
    )


def profile_badge_html(name: str, role_line: str) -> str:
    return (
        '<div class="profile-badge">'
        f'<div class="profile-avatar">{esc(initials_of(name))}</div>'
        "<div>"
        f'<div class="profile-name">{esc(name)}</div>'
        f'<div class="profile-role">{esc(role_line)}</div>'
        "</div></div>"
    )
