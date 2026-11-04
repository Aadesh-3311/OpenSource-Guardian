"""Unit tests for Switch REST Operations Client."""

import pytest
import httpx
from pydantic import SecretStr
from src.guardian.adapters.switch_client import (
    SwitchAuthError,
    SwitchClientError,
    SwitchConflictError,
    SwitchNetworkError,
    SwitchNotFoundError,
    SwitchRestClient,
)


@pytest.mark.anyio
async def test_post_message_success_ops_endpoint() -> None:
    """Verify posting message via the standard /ops/post_message endpoint."""
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.url.path == "/agents/agent-123/ops/post_message":
            return httpx.Response(200, json={"result": {"message_id": "msg-001"}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            api_key="secret-api-key",
            connection_id="conn-uuid-1",
            client=http_client,
        )

        res = await client.post_message(room_id="room-general", content="Hello room!", thread_id="thread-abc")
        assert res["result"]["message_id"] == "msg-001"

        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.headers["Authorization"] == "Bearer secret-api-key"
        assert req.headers["X-Switch-Connection-Id"] == "conn-uuid-1"
        assert req.headers["Content-Type"] == "application/json"


@pytest.mark.anyio
async def test_post_message_fallback_to_direct_message() -> None:
    """Verify fallback to /agents/{agent_id}/message when /ops/post_message is unavailable."""
    captured_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_paths.append(request.url.path)
        if request.url.path == "/agents/agent-123/ops/post_message":
            return httpx.Response(404, json={"detail": "Unknown operation"})
        if request.url.path == "/agents/agent-123/message":
            return httpx.Response(200, json={"status": "sent", "id": "fallback-msg-1"})
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            api_key="secret-api-key",
            client=http_client,
        )

        res = await client.post_message(room_id="room-general", content="Fallback test")
        assert res["id"] == "fallback-msg-1"
        assert captured_paths == [
            "/agents/agent-123/ops/post_message",
            "/agents/agent-123/message",
        ]


@pytest.mark.anyio
async def test_connect_to_room_success() -> None:
    """Verify connect_to_room operation."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agents/agent-123/ops/connect_to_room":
            return httpx.Response(200, json={"result": {"room_id": "room-target", "status": "connected"}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            api_key="secret-api-key",
            client=http_client,
        )

        res = await client.connect_to_room("room-target")
        assert res["result"]["status"] == "connected"


@pytest.mark.anyio
async def test_auth_error_handling() -> None:
    """Verify 401 and 403 responses raise SwitchAuthError without leaking credentials."""
    secret = "super-secret-token-123"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            api_key=secret,
            client=http_client,
        )

        with pytest.raises(SwitchAuthError) as exc_info:
            await client.connect_to_room("room-1")

        assert "Authentication failed" in str(exc_info.value)
        assert secret not in str(exc_info.value)


@pytest.mark.anyio
async def test_conflict_error_handling_409() -> None:
    """Verify 409 responses raise SwitchConflictError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"code": "taken_over", "detail": "Connection superseded"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            client=http_client,
        )

        with pytest.raises(SwitchConflictError, match="Conflict occurred"):
            await client.connect_to_room("room-1")


@pytest.mark.anyio
async def test_network_and_timeout_error_handling() -> None:
    """Verify connection failure raises SwitchNetworkError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out after 10.0s")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="agent-123",
            client=http_client,
        )

        with pytest.raises(SwitchNetworkError, match="Network error"):
            await client.post_message("room-1", "hello")


@pytest.mark.anyio
async def test_missing_agent_id_validation() -> None:
    """Verify operations fail gracefully when agent_id is empty."""
    client = SwitchRestClient(agent_id="")
    with pytest.raises(SwitchClientError, match="SWITCH_AGENT_ID is not configured"):
        await client.post_message("room-1", "hello")
