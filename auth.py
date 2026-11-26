"""Supabase Auth email/password, invite/recovery and session lifecycle.

Passwords never enter our database. Only GoTrue receives them over HTTPS.
JWT/refresh tokens live in that user's Streamlit server-side session only.
"""
from __future__ import annotations
import time
import streamlit as st
from cloud import CloudClient, CloudError
from settings import load_settings


def client() -> CloudClient:
    session = st.session_state.get("auth_session") or {}
    return CloudClient(load_settings(), session.get("access_token", ""))


def _store(payload: dict) -> None:
    if not payload.get("access_token") or not payload.get("refresh_token"):
        raise CloudError("Authentication did not return a valid session.")
    st.session_state["auth_session"] = {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_at": payload.get("expires_at") or time.time() + payload.get("expires_in", 3600),
    }


def clear_session() -> None:
    st.session_state.pop("auth_session", None)
    st.session_state.pop("user", None)
    st.session_state.pop("password_setup", None)


def identity() -> dict:
    c = client()
    person = c.request("GET", "/auth/v1/user")
    profiles = c.rows("profiles", {"id": f"eq.{person['id']}", "select": "id,role,display_name,student_id,active"})
    if not profiles or not profiles[0]["active"]:
        raise CloudError("Your school account is not active or has not been provisioned. Contact your teacher.", 403)
    user = profiles[0]
    user["email"] = person.get("email", "")
    if user["role"] == "student":
        roster = c.rows("students", {"id": f"eq.{user['student_id']}", "select": "batch"})
        if not roster:
            raise CloudError("Your student record is unavailable. Contact your teacher.", 403)
        user["batch"] = roster[0]["batch"]
    return user


def authenticate(email: str, password: str) -> tuple[dict | None, str | None]:
    email = (email or "").strip().lower()
    if not email or not password:
        return None, "Please enter your email address and password."
    c = CloudClient(load_settings())
    try:
        payload = c.request("POST", "/auth/v1/token", params={"grant_type": "password"},
                            body={"email": email, "password": password}, authenticated=False)
        _store(payload)
        return identity(), None
    except CloudError as error:
        clear_session()
        if error.status in (400, 401, 422):
            return None, "Incorrect email or password, or the account is unavailable."
        return None, str(error)


def ensure_session() -> dict | None:
    session = st.session_state.get("auth_session")
    if not session:
        return None
    try:
        if session["expires_at"] <= time.time() + 60:
            payload = client().request(
                "POST", "/auth/v1/token", params={"grant_type": "refresh_token"},
                body={"refresh_token": session["refresh_token"]}, authenticated=False,
            )
            _store(payload)
        # Validate user server-side and re-read role/active status every rerun.
        user = identity()
        st.session_state["user"] = user
        return user
    except CloudError as error:
        if error.status in (400, 401, 403, 422):
            clear_session()
            st.session_state["auth_notice"] = "Please sign in again or contact your teacher if your account was disabled."
            return None
        raise


def consume_email_link() -> bool:
    token_hash = st.query_params.get("token_hash")
    if not token_hash:
        return False
    link_type = st.query_params.get("type", "")
    # Remove sensitive one-time material from the URL before any further rerun.
    del st.query_params["token_hash"]
    if "type" in st.query_params:
        del st.query_params["type"]
    if link_type not in ("invite", "recovery") or not 16 <= len(token_hash) <= 1024:
        raise CloudError("This account link is invalid. Request a new password link.")
    clear_session()
    try:
        payload = CloudClient(load_settings()).request(
            "POST", "/auth/v1/verify", body={"token_hash": token_hash, "type": link_type},
            authenticated=False,
        )
        _store(payload)
        st.session_state["user"] = identity()
        st.session_state["password_setup"] = True
        return True
    except CloudError:
        clear_session()
        raise CloudError("This account link is invalid, expired, or already used. Request a new password link.") from None


def request_password_reset(email: str) -> None:
    email = (email or "").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise ValueError("Enter a valid email address.")
    settings = load_settings()
    try:
        CloudClient(settings).request("POST", "/auth/v1/recover", body={"email": email},
                                      params={"redirect_to": settings.app_url + "/"}, authenticated=False)
    except CloudError as error:
        # Do not reveal whether the account exists. Rate/network errors remain actionable.
        if error.status not in (400, 404, 422):
            raise


def change_password(password: str, confirmation: str, current_password: str | None = None) -> None:
    if password != confirmation:
        raise ValueError("The passwords do not match.")
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Use between 12 and 128 characters; a long unique passphrase is recommended.")
    if not st.session_state.get("password_setup"):
        if not current_password:
            raise ValueError("Enter your current password to confirm this change.")
        user = identity()
        try:
            payload = CloudClient(load_settings()).request(
                "POST", "/auth/v1/token", params={"grant_type": "password"},
                body={"email": user["email"], "password": current_password}, authenticated=False,
            )
        except CloudError as error:
            if error.status in (400, 401, 422):
                raise ValueError("Your current password could not be verified.") from None
            raise
        if payload.get("user", {}).get("id") != user["id"]:
            raise CloudError("Account verification failed.", 403)
        _store(payload)
    client().request("PUT", "/auth/v1/user", body={"password": password})
    st.session_state.pop("password_setup", None)


def sign_out() -> None:
    try:
        if st.session_state.get("auth_session"):
            client().request("POST", "/auth/v1/logout", params={"scope": "local"})
    except CloudError:
        pass
    finally:
        clear_session()
