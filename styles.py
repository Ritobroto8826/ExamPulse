"""Session-scoped CSS and application chrome. Theme never mutates global config."""
from __future__ import annotations

from pathlib import Path
import streamlit as st
from theme import palette

_CSS_PATH = Path(__file__).resolve().parent / "styles.css"


def theme_mode() -> str:
    return "dark" if st.session_state.get("dark_mode", False) else "light"


def init_theme() -> None:
    if "dark_mode" not in st.session_state:
        st.session_state["dark_mode"] = st.query_params.get("theme", "light") == "dark"


def _save_theme() -> None:
    # Keep the preference across refreshes, without third-party JS or cookies.
    st.query_params["theme"] = theme_mode()


def inject_css() -> None:
    mode = theme_mode()
    tokens = palette(mode)
    variables = ";".join(f"--{key}:{value}" for key, value in tokens.items())
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(
        f'<style>{css}\n:root{{{variables};color-scheme:{mode};}}'
        f'</style><span id="ep-theme-{mode}" aria-hidden="true"></span>',
        unsafe_allow_html=True,
    )


def render_app_chrome() -> None:
    with st.container(key="app_topbar"):
        brand, control = st.columns([4, 1], vertical_alignment="center")
        with brand:
            st.markdown(
                '<div class="app-brand"><div class="brand-mark" aria-hidden="true">'
                '<svg width="22" height="22" viewBox="0 0 24 24" fill="none">'
                '<path d="M3 16h4l3-9 4 13 3-9h4" stroke="currentColor" '
                'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
                '</svg></div><div><div class="brand-name">BrightSteps'
                '<span class="brand-tag">PRIVATE TUITION</span></div>'
                '<div class="brand-caption">Small batches, big leaps.</div></div></div>',
                unsafe_allow_html=True,
            )
        with control:
            st.toggle("Dark mode", key="dark_mode", on_change=_save_theme)
