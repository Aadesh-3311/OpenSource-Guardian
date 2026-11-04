"""Unit tests for Switch Agent Bridge WebSocket protocol models and parser."""

import pytest
from src.guardian.adapters.switch_protocol import (
    ConnectionStateFrame,
    DomainEventFrame,
    EvictedFrame,
    GapFrame,
    MessagePayload,
    PingFrame,
    PongFrame,
    RefusedFrame,
    SubscriptionChangedFrame,
    SwitchProtocolError,
    create_pong_frame,
    parse_switch_frame,
)


def test_parse_valid_message_domain_event() -> None:
    """Verify parsing of standard Switch message domain event with attachments and thread_id."""
    raw = {
        "event": "message",
        "data": {
            "type": "message",
            "room_id": "room-123",
            "bridge_id": "bridge-discord-1",
            "channel_type": "channel_public",
            "payload": {
                "addressed": True,
                "sender": "@switch-user-456:deploy",
                "sender_name": "Alice",
                "message_id": "msg-789",
                "body": "@guardian review PR #42",
                "timestamp": 1700000000000,
                "thread_id": "thread-001",
                "attachments": [
                    {
                        "filename": "patch.diff",
                        "mimetype": "text/x-diff",
                        "size": 1024,
                    }
                ],
            },
            "sequence": 4813,
        },
        "id": 4813,
    }

    frame = parse_switch_frame(raw)
    assert isinstance(frame, DomainEventFrame)
    assert frame.event == "message"
    assert frame.id == 4813
    assert frame.data.room_id == "room-123"
    assert frame.data.sequence == 4813

    payload = frame.data.payload
    assert isinstance(payload, MessagePayload)
    assert payload.addressed is True
    assert payload.sender_name == "Alice"
    assert payload.body == "@guardian review PR #42"
    assert payload.thread_id == "thread-001"
    assert len(payload.attachments) == 1
    assert payload.attachments[0].filename == "patch.diff"


def test_parse_command_and_room_join_domain_events() -> None:
    """Verify parsing of command and room_join events."""
    # 1. Command event
    cmd_raw = {
        "event": "command",
        "data": {
            "type": "command",
            "room_id": "room-123",
            "payload": {
                "command": "reset",
                "args": "reviewer",
                "user_id": "@admin:deploy",
                "user_name": "Admin",
            },
            "sequence": 5001,
        },
        "id": 5001,
    }
    cmd_frame = parse_switch_frame(cmd_raw)
    assert isinstance(cmd_frame, DomainEventFrame)
    assert cmd_frame.data.sequence == 5001

    # 2. Room join event
    join_raw = {
        "event": "room_join",
        "data": {
            "type": "room_join",
            "room_id": "room-123",
            "payload": {
                "member": "@switch-agent-guardian:deploy",
                "member_name": "OpenSource Guardian",
                "listening": True,
            },
            "sequence": 5002,
        },
        "id": 5002,
    }
    join_frame = parse_switch_frame(join_raw)
    assert isinstance(join_frame, DomainEventFrame)
    assert join_frame.data.sequence == 5002


def test_parse_connection_state_frame() -> None:
    """Verify parsing of connection_state control frame."""
    raw = {
        "event": "connection_state",
        "connection_id": "conn-uuid-1234",
        "agent_id": "agent-guardian-id",
        "generation": "gen-1",
        "scope": "all",
        "filter": "addressed",
        "rooms": ["room-a", "room-b"],
        "cursor": 100,
        "protocol": 6,
        "heartbeat_interval_seconds": 2.0,
    }

    frame = parse_switch_frame(raw)
    assert isinstance(frame, ConnectionStateFrame)
    assert frame.connection_id == "conn-uuid-1234"
    assert frame.rooms == ["room-a", "room-b"]
    assert frame.cursor == 100
    assert frame.heartbeat_interval_seconds == 2.0


def test_ping_pong_frames() -> None:
    """Verify ping frame parsing and pong frame creation."""
    # Ping
    ping_frame = parse_switch_frame('{"type": "ping"}')
    assert isinstance(ping_frame, PingFrame)

    # Pong frame generator
    pong_dict = create_pong_frame(cursor=4813)
    assert pong_dict == {"type": "pong", "cursor": 4813}

    pong_frame = parse_switch_frame(pong_dict)
    assert isinstance(pong_frame, PongFrame)
    assert pong_frame.cursor == 4813


def test_control_frames_evicted_gap_refused() -> None:
    """Verify evicted, gap, refused, and subscription_changed control frames."""
    # Evicted terminal (taken_over)
    evicted_taken = parse_switch_frame({"type": "evicted", "code": "taken_over", "reason": "Another instance connected"})
    assert isinstance(evicted_taken, EvictedFrame)
    assert evicted_taken.is_terminal is True

    # Evicted recoverable (heartbeat_lapsed)
    evicted_lapsed = parse_switch_frame({"type": "evicted", "code": "heartbeat_lapsed"})
    assert isinstance(evicted_lapsed, EvictedFrame)
    assert evicted_lapsed.is_terminal is False

    # Gap
    gap = parse_switch_frame({
        "type": "gap",
        "from_sequence": 10,
        "resumed_at": 50,
        "rooms": ["room-1"],
    })
    assert isinstance(gap, GapFrame)
    assert gap.resumed_at == 50

    # Refused
    refused = parse_switch_frame({"type": "refused", "status": 409, "detail": "Protocol mismatch"})
    assert isinstance(refused, RefusedFrame)
    assert refused.status == 409

    # Subscription changed
    sub = parse_switch_frame({"type": "subscription_changed", "rooms": ["room-x", "room-y"]})
    assert isinstance(sub, SubscriptionChangedFrame)
    assert len(sub.rooms) == 2


def test_malformed_and_invalid_frames_raise_protocol_error() -> None:
    """Verify graceful error handling on malformed JSON or unknown frame payloads."""
    # 1. Invalid JSON syntax
    with pytest.raises(SwitchProtocolError, match="Malformed JSON"):
        parse_switch_frame("{not-valid-json}")

    # 2. Non-dict JSON
    with pytest.raises(SwitchProtocolError, match="must be a JSON object"):
        parse_switch_frame("[1, 2, 3]")

    # 3. Unrecognized event/type
    with pytest.raises(SwitchProtocolError, match="Unknown or unrecognized"):
        parse_switch_frame({"event": "unknown_event_xyz"})

    # 4. Incomplete domain event (missing 'id' or 'data')
    with pytest.raises(SwitchProtocolError):
        parse_switch_frame({"event": "message", "data": {}})
