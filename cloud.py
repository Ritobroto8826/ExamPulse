"""Supabase HTTP transport. A client belongs to one session; no cached JWTs.

Read-only GETs may be paginated. Mutations are never blindly retried: a network
failure can leave the commit outcome unknown, so the user should refresh first.
"""
from __future__ import annotations
import logging
from typing import Any
import httpx
from settings import Settings

log = logging.getLogger(__name__)


class CloudError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class CloudClient:
    def __init__(self, settings: Settings, access_token: str = "", transport=None):
        self.settings = settings
        self.access_token = access_token
        self.transport = transport  # injectable only for tests

    def request(self, method: str, path: str, *, body: Any = None,
                params: dict | None = None, headers: dict | None = None,
                authenticated: bool = True):
        if authenticated and not self.access_token:
            raise CloudError("Please sign in to continue.", 401)
        request_headers = {"apikey": self.settings.public_key, "Accept": "application/json"}
        if self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        request_headers.update(headers or {})
        try:
            with httpx.Client(timeout=httpx.Timeout(20, connect=8), transport=self.transport,
                              follow_redirects=False) as client:
                result = client.request(method, self.settings.url + path,
                                        json=body, params=params, headers=request_headers)
        except httpx.HTTPError:
            # No raw exception logging: URLs/headers/body may contain secrets.
            raise CloudError("Supabase could not be reached. Refresh to check whether your last change was saved before trying again.") from None
        if not result.is_success:
            log.warning("Supabase operation failed: method=%s endpoint=%s status=%s",
                        method, path.split("?")[0], result.status_code)
            if result.status_code == 429:
                message = "Too many requests. Please wait and try again."
            elif result.status_code == 401:
                message = "Your session has expired. Please sign in again."
            elif result.status_code == 403:
                message = "Your account does not have permission for this action."
            elif result.status_code == 409:
                message = "This record conflicts with an existing record. Refresh and check for duplicates."
            else:
                message = "The operation could not be completed. Check the entered values and the deployment setup."
            raise CloudError(message, result.status_code)
        if not result.content:
            return None
        try:
            return result.json()
        except ValueError:
            raise CloudError("Supabase returned an unexpected response. Please contact your administrator.") from None

    def rest(self, method: str, table: str, *, body=None, params=None, prefer=None):
        return self.request(method, "/rest/v1/" + table, body=body, params=params,
                            headers={"Prefer": prefer} if prefer else None)

    def rows(self, table: str, params: dict | None = None, max_rows: int = 100_000) -> list[dict]:
        """Never silently truncate at PostgREST's default 1,000-row response cap."""
        output = []
        while True:
            chunk = self.rest("GET", table, params={**(params or {}),
                              "limit": 500, "offset": len(output)})
            if not isinstance(chunk, list):
                raise CloudError("Unexpected database result.")
            output.extend(chunk)
            if len(output) > max_rows:
                raise CloudError("This dataset exceeds the interactive row limit. Ask your administrator to add server-side reporting filters.")
            if len(chunk) < 500:
                return output

    def rpc(self, name: str, body: dict):
        return self.rest("POST", "rpc/" + name, body=body)

    def rpc_rows(self, name: str, body: dict, max_rows: int = 100_000) -> list[dict]:
        """Pagination for read-only table-valued RPCs, never mutation RPCs."""
        output = []
        while True:
            chunk = self.rest("POST", "rpc/" + name, body=body,
                              params={"limit": 500, "offset": len(output)})
            if not isinstance(chunk, list):
                raise CloudError("Unexpected comparison result.")
            output.extend(chunk)
            if len(output) > max_rows:
                raise CloudError("Comparison exceeds the interactive row limit. Add batch-level server filtering.")
            if len(chunk) < 500:
                return output
