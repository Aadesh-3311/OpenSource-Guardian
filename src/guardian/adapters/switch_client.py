"""Switch Agent Bridge client supporting HTTP REST operations and WebSocket streams."""

from __future__ import annotations

import logging
from typing import Any
import httpx
from pydantic import SecretStr
from src.guardian.config import Settings, get_settings

logger = logging.getLogger("guardian.adapters.switch_client")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class SwitchClientError(Exception):
    """Base exception for Switch client operations."""


class SwitchAuthError(SwitchClientError):
    """Raised when authentication against Switch fails (401 or 403)."""


class SwitchNotFoundError(SwitchClientError):
    """Raised when an agent, room, or operation is not found (404)."""


class SwitchConflictError(SwitchClientError):
    """Raised when a conflict occurs, such as a dead or overtaken connection (409)."""


class SwitchNetworkError(SwitchClientError):
    """Raised on connection timeout or network connectivity issues."""


# ---------------------------------------------------------------------------
# Switch REST Operations Client
# ---------------------------------------------------------------------------

class SwitchRestClient:
    """Async HTTP client for Switch Agent Bridge REST operations."""

    def __init__(
        self,
        base_url: str | None = None,
        agent_id: str | None = None,
        api_key: SecretStr | str | None = None,
        connection_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        settings: Settings = get_settings()
        self.base_url = (base_url or settings.switch_api_url).rstrip("/")
        self.agent_id = agent_id or settings.switch_agent_id or ""

        raw_key = api_key if api_key is not None else settings.switch_api_key
        if isinstance(raw_key, str):
            self.api_key = SecretStr(raw_key) if raw_key else None
        else:
            self.api_key = raw_key

        self.connection_id = connection_id or settings.switch_connection_id
        self._injected_client = client is not None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the underlying HTTPX async client."""
        return self._client

    async def __aenter__(self) -> SwitchRestClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client if managed internally."""
        if not self._injected_client and not self._client.is_closed:
            await self._client.aclose()

    def _get_headers(self) -> dict[str, str]:
        """Construct standard Switch authorization and connection headers."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        if self.connection_id:
            headers["X-Switch-Connection-Id"] = self.connection_id
        return headers

    def _handle_response_error(self, response: httpx.Response, action_description: str) -> None:
        """Map HTTP error status codes to typed Switch domain exceptions without leaking credentials."""
        status = response.status_code
        if status in (401, 403):
            raise SwitchAuthError(
                f"Authentication failed during {action_description} (status {status}). "
                "Check SWITCH_API_KEY and agent permissions."
            )
        if status == 404:
            raise SwitchNotFoundError(
                f"Resource not found during {action_description} (status 404). "
                f"Check agent_id '{self.agent_id}' or target entity."
            )
        if status == 409:
            raise SwitchConflictError(
                f"Conflict occurred during {action_description} (status 409). "
                "Connection ID may have been superseded or room is claimed."
            )
        if status >= 400:
            raise SwitchClientError(
                f"Switch API error during {action_description} (status {status}): {response.text[:200]}"
            )

    async def post_message(
        self,
        room_id: str,
        content: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to a Switch room via operations registry or direct fallback."""
        if not self.agent_id:
            raise SwitchClientError("Cannot post message: SWITCH_AGENT_ID is not configured.")

        payload: dict[str, Any] = {
            "room_id": room_id,
            "content": content,
        }
        if thread_id:
            payload["thread_id"] = thread_id

        headers = self._get_headers()
        url = f"{self.base_url}/agents/{self.agent_id}/ops/post_message"

        try:
            response = await self._client.post(url, json=payload, headers=headers)
            if response.status_code == 404:
                # Fallback to direct message endpoint /agents/{agent_id}/message
                fallback_url = f"{self.base_url}/agents/{self.agent_id}/message"
                response = await self._client.post(fallback_url, json=payload, headers=headers)

            if response.status_code >= 400:
                self._handle_response_error(response, f"post_message to room '{room_id}'")

            try:
                return response.json()
            except Exception:
                return {"status": "success", "room_id": room_id}

        except httpx.RequestError as err:
            raise SwitchNetworkError(f"Network error while posting message to Switch: {err}") from err

    async def connect_to_room(self, room_id: str) -> dict[str, Any]:
        """Claim and connect to a room via Switch operations."""
        if not self.agent_id:
            raise SwitchClientError("Cannot connect to room: SWITCH_AGENT_ID is not configured.")

        payload = {"room_id": room_id}
        headers = self._get_headers()
        url = f"{self.base_url}/agents/{self.agent_id}/ops/connect_to_room"

        try:
            response = await self._client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                self._handle_response_error(response, f"connect_to_room '{room_id}'")

            try:
                return response.json()
            except Exception:
                return {"status": "connected", "room_id": room_id}

        except httpx.RequestError as err:
            raise SwitchNetworkError(f"Network error while connecting to room on Switch: {err}") from err
