"""Public connection configuration only. This app never needs a service-role key."""
from __future__ import annotations
import base64
from dataclasses import dataclass
import json
import os
from urllib.parse import urlparse
import streamlit as st


class ConfigurationError(ValueError):
    pass


def _value(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


@dataclass(frozen=True)
class Settings:
    url: str
    public_key: str
    app_url: str


def load_settings() -> Settings:
    url = _value("SUPABASE_URL").rstrip("/")
    key = _value("SUPABASE_PUBLISHABLE_KEY") or _value("SUPABASE_ANON_KEY")
    app_url = _value("APP_URL").rstrip("/")
    if not url or not key or not app_url:
        raise ConfigurationError("Set SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and APP_URL in Streamlit Secrets.")
    for label, value in [("SUPABASE_URL", url), ("APP_URL", app_url)]:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ConfigurationError(f"{label} must be an HTTPS URL without embedded credentials.")
        if parsed.query or parsed.fragment:
            raise ConfigurationError(f"{label} must not contain query parameters or fragments.")
    # Safety check, NOT token verification: privileged keys must never be used
    # for routine browser-user data access, because they bypass all RLS rules.
    role = None
    if key.count(".") == 2:
        try:
            raw = key.split(".")[1]
            role = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))).get("role")
        except (ValueError, json.JSONDecodeError):
            raise ConfigurationError("The Supabase API key is malformed.") from None
    if key.startswith("sb_secret_") or role == "service_role":
        raise ConfigurationError("Use a publishable/anon key, never a secret/service-role key in Streamlit.")
    if not key.startswith("sb_publishable_") and role != "anon":
        raise ConfigurationError("Provide a Supabase publishable key or legacy anon key.")
    return Settings(url, key, app_url)
