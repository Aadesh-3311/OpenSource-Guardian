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
    SwitchWebSocketClient,
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


# ---------------------------------------------------------------------------
# Switch WebSocket Client Tests
# ---------------------------------------------------------------------------

class MockWebSocket:
    """Mock WebSocket interface for testing frame handling and message dispatch."""

    def __init__(self, incoming_messages: list[str]) -> None:
        self.incoming = incoming_messages
        self.sent: list[str] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.incoming:
            return self.incoming.pop(0)
        raise StopAsyncIteration

    async def send(self, message: str) -> None:
        self.sent.append(message)


def test_ws_url_and_headers_construction() -> None:
    """Verify WebSocket URL and authorization header construction."""
    ws_client = SwitchWebSocketClient(
        base_url="https://api.switchagents.ai",
        agent_id="guardian-1",
        api_key="secret-token-key",
        rooms=["room-1", "room-2"],
        connection_id="fixed-uuid",
        scope="all",
        filter_mode="addressed",
    )

    url = ws_client.build_ws_url()
    assert url.startswith("wss://api.switchagents.ai/agents/guardian-1/connection/ws?")
    assert "connection_id=fixed-uuid" in url
    assert "rooms=room-1%2Croom-2" in url or "rooms=room-1,room-2" in url
    assert "scope=all" in url
    assert "filter=addressed" in url
    assert "start_from=head" in url

    # Test cursor and generation updates
    ws_client.cursor = 4813
    ws_client.generation = "gen-abc"
    updated_url = ws_client.build_ws_url()
    assert "start_from=4813" in updated_url
    assert "expected_generation=gen-abc" in updated_url

    # Check headers
    headers = ws_client.build_headers()
    assert headers["Authorization"] == "Bearer secret-token-key"


@pytest.mark.anyio
async def test_ws_handle_ping_frame_sends_immediate_pong() -> None:
    """Verify ping frame causes an immediate pong response containing current cursor."""
    ws_client = SwitchWebSocketClient(agent_id="guardian-1")
    ws_client.cursor = 105

    mock_ws = MockWebSocket([])
    await ws_client.handle_frame('{"type": "ping"}', mock_ws)

    assert len(mock_ws.sent) == 1
    import json
    pong = json.loads(mock_ws.sent[0])
    assert pong == {"type": "pong", "cursor": 105}


@pytest.mark.anyio
async def test_ws_handle_connection_state_and_gap() -> None:
    """Verify connection_state and gap frames update generation, covered rooms, and cursor."""
    ws_client = SwitchWebSocketClient(agent_id="guardian-1")
    mock_ws = MockWebSocket([])

    # 1. Connection state
    state_payload = """
    {
        "event": "connection_state",
        "connection_id": "c1",
        "agent_id": "guardian-1",
        "generation": "gen-99",
        "rooms": ["room-a", "room-b"],
        "cursor": 200
    }
    """
    await ws_client.handle_frame(state_payload, mock_ws)
    assert ws_client.generation == "gen-99"
    assert ws_client.covered_rooms == ["room-a", "room-b"]
    assert ws_client.cursor == 200

    # 2. Gap frame
    gap_payload = """
    {
        "type": "gap",
        "from_sequence": 200,
        "resumed_at": 350,
        "rooms": ["room-a"],
        "reason": "buffer pruned"
    }
    """
    await ws_client.handle_frame(gap_payload, mock_ws)
    assert ws_client.cursor == 350


@pytest.mark.anyio
async def test_ws_handle_evicted_frame_terminal() -> None:
    """Verify terminal eviction (taken_over) terminates the client immediately."""
    ws_client = SwitchWebSocketClient(agent_id="guardian-1")
    ws_client._running = True
    mock_ws = MockWebSocket([])

    evicted_payload = '{"type": "evicted", "code": "taken_over", "reason": "Another open won"}'
    await ws_client.handle_frame(evicted_payload, mock_ws)

    assert ws_client._terminated is True
    assert ws_client._running is False


@pytest.mark.anyio
async def test_ws_dispatch_domain_event_to_callback() -> None:
    """Verify domain event advances cursor and triggers registered on_event callback."""
    dispatched_events = []

    async def on_event(event) -> None:
        dispatched_events.append(event)

    ws_client = SwitchWebSocketClient(agent_id="guardian-1", on_event=on_event)
    mock_ws = MockWebSocket([])

    msg_payload = """
    {
        "event": "message",
        "data": {
            "type": "message",
            "room_id": "room-1",
            "payload": {
                "addressed": true,
                "sender": "@user:host",
                "body": "Hello guardian"
            },
            "sequence": 505
        },
        "id": 505
    }
    """
    await ws_client.handle_frame(msg_payload, mock_ws)

    assert ws_client.cursor == 505
    assert len(dispatched_events) == 1
    assert dispatched_events[0].id == 505
    assert dispatched_events[0].data.payload.body == "Hello guardian"


@pytest.mark.anyio
async def test_ws_listen_reads_sequence_of_frames() -> None:
    """Verify listen loop processes stream of incoming frames sequentially."""
    frames = [
        '{"type": "ping"}',
        '{"event": "message", "data": {"type": "message", "room_id": "r1", "payload": {"body": "m1"}, "sequence": 1}, "id": 1}',
        '{"type": "ping"}',
    ]
    mock_ws = MockWebSocket(frames)
    ws_client = SwitchWebSocketClient(agent_id="guardian-1")
    ws_client._running = True

    await ws_client.listen(mock_ws)

    assert ws_client.cursor == 1
    assert len(mock_ws.sent) == 2  # Two pongs sent

