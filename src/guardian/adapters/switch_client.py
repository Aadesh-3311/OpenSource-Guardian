"""Switch Agent Bridge client supporting HTTP REST operations and WebSocket streams."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode, urlparse, urlunparse
import httpx
from pydantic import SecretStr
import websockets
from src.guardian.adapters.switch_protocol import (
    ConnectionStateFrame,
    DomainEventFrame,
    EvictedFrame,
    GapFrame,
    PingFrame,
    RefusedFrame,
    SwitchFrame,
    SwitchProtocolError,
    create_pong_frame,
    parse_switch_frame,
)
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


# ---------------------------------------------------------------------------
# Switch WebSocket Connection Client
# ---------------------------------------------------------------------------

class SwitchWebSocketClient:
    """Async WebSocket client connecting to the Switch Agent Bridge event stream."""

    def __init__(
        self,
        base_url: str | None = None,
        agent_id: str | None = None,
        api_key: SecretStr | str | None = None,
        rooms: str | list[str] | None = None,
        connection_id: str | None = None,
        scope: str = "all",
        filter_mode: str = "all",
        on_event: Callable[[DomainEventFrame], Awaitable[None]] | None = None,
    ) -> None:
        settings: Settings = get_settings()
        self.base_url = (base_url or settings.switch_api_url).rstrip("/")
        self.agent_id = agent_id or settings.switch_agent_id or ""

        raw_key = api_key if api_key is not None else settings.switch_api_key
        if isinstance(raw_key, str):
            self.api_key = SecretStr(raw_key) if raw_key else None
        else:
            self.api_key = raw_key

        if isinstance(rooms, list):
            self.rooms = ",".join(rooms)
        else:
            self.rooms = rooms or settings.switch_rooms

        self.connection_id = connection_id or settings.switch_connection_id or str(uuid.uuid4())
        self.scope = scope
        self.filter_mode = filter_mode
        self.on_event = on_event

        self.cursor: int = 0
        self.generation: int | str | None = None
        self.covered_rooms: list[str] = []

        self._running: bool = False
        self._terminated: bool = False
        self._active_ws: Any = None

    def build_ws_url(self) -> str:
        """Construct the full WebSocket URL including query parameters."""
        parsed = urlparse(self.base_url)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"/agents/{self.agent_id}/connection/ws"

        query_params: dict[str, str] = {
            "connection_id": self.connection_id,
            "scope": self.scope,
            "filter": self.filter_mode,
        }
        if self.rooms:
            query_params["rooms"] = self.rooms
        if self.cursor > 0:
            query_params["start_from"] = str(self.cursor)
        else:
            query_params["start_from"] = "head"

        if self.generation is not None:
            query_params["expected_generation"] = str(self.generation)

        query_string = urlencode(query_params)
        return urlunparse((ws_scheme, parsed.netloc, path, "", query_string, ""))

    def build_headers(self) -> dict[str, str]:
        """Return HTTP headers for opening the WebSocket handshake."""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        return headers

    async def handle_frame(self, raw_frame: str | bytes, websocket: Any) -> None:
        """Process an inbound text frame, update cursor, answer pings, or dispatch domain events."""
        try:
            frame: SwitchFrame = parse_switch_frame(raw_frame)
        except SwitchProtocolError as err:
            logger.warning("Ignoring malformed Switch frame: %s", err)
            return

        # 1. Heartbeat Ping -> Immediate Pong
        if isinstance(frame, PingFrame):
            pong_payload = json.dumps(create_pong_frame(self.cursor))
            await websocket.send(pong_payload)
            logger.debug("Answered server ping with pong (cursor=%d)", self.cursor)
            return

        # 2. Connection State (First frame)
        if isinstance(frame, ConnectionStateFrame):
            self.generation = frame.generation
            self.covered_rooms = frame.rooms
            if frame.cursor is not None and frame.cursor > self.cursor:
                self.cursor = frame.cursor
            logger.info(
                "Connected to Switch. generation=%s, covered_rooms=%s, cursor=%d",
                self.generation,
                self.covered_rooms,
                self.cursor,
            )
            return

        # 3. Gap frame -> Update cursor
        if isinstance(frame, GapFrame):
            logger.warning(
                "Switch event buffer gap detected: from %d, resuming at %d (reason: %s)",
                frame.from_sequence,
                frame.resumed_at,
                frame.reason,
            )
            self.cursor = max(self.cursor, frame.resumed_at)
            return

        # 4. Evicted frame -> Check terminal condition
        if isinstance(frame, EvictedFrame):
            logger.warning("Evicted by Switch: code=%s, reason=%s", frame.code, frame.reason)
            if frame.is_terminal:
                self._terminated = True
                self._running = False
            return

        # 5. Refused frame
        if isinstance(frame, RefusedFrame):
            logger.error("Connection refused by Switch: status=%d, detail=%s", frame.status, frame.detail)
            self._terminated = True
            self._running = False
            return

        # 6. Domain Event -> Update cursor & dispatch
        if isinstance(frame, DomainEventFrame):
            self.cursor = max(self.cursor, frame.id, frame.data.sequence)
            if self.on_event is not None:
                try:
                    await self.on_event(frame)
                except Exception as err:
                    logger.error("Error in Switch domain event callback: %s", err, exc_info=True)

    async def listen(self, websocket: Any) -> None:
        """Continuously read frames from an active WebSocket until disconnection."""
        self._active_ws = websocket
        async for raw_message in websocket:
            if not self._running or self._terminated:
                break
            await self.handle_frame(raw_message, websocket)

    async def run_loop(
        self,
        max_reconnects: int | None = None,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        """Run WebSocket connection loop with automatic reconnect and cursor persistence."""
        if not self.agent_id:
            raise SwitchClientError("Cannot start Switch WebSocket client: SWITCH_AGENT_ID is not configured.")

        self._running = True
        self._terminated = False
        reconnect_attempts = 0
        backoff = initial_backoff

        while self._running and not self._terminated:
            ws_url = self.build_ws_url()
            headers = self.build_headers()

            try:
                logger.info("Connecting to Switch WebSocket: %s", ws_url)
                async with websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    ping_interval=None,  # Switch uses application-level JSON ping frames
                ) as ws:
                    reconnect_attempts = 0
                    backoff = initial_backoff
                    await self.listen(ws)

            except (websockets.exceptions.WebSocketException, OSError) as err:
                logger.warning("Switch WebSocket disconnected: %s", err)

            except Exception as err:
                logger.error("Unexpected error in Switch WebSocket connection: %s", err, exc_info=True)

            finally:
                self._active_ws = None

            if not self._running or self._terminated:
                break

            reconnect_attempts += 1
            if max_reconnects is not None and reconnect_attempts >= max_reconnects:
                logger.error("Maximum reconnection attempts (%d) reached. Stopping.", max_reconnects)
                break

            logger.info("Reconnecting in %.1fs (attempt %d)...", backoff, reconnect_attempts)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)

        self._running = False

    def stop(self) -> None:
        """Stop the running WebSocket loop and close active connection."""
        self._running = False
        self._terminated = True

