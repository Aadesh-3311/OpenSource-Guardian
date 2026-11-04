"""Typed protocol models and parser for Switch Agent Bridge WebSocket frames."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SwitchProtocolError(Exception):
    """Raised when an unparseable or severely malformed Switch frame is received."""


# ---------------------------------------------------------------------------
# Domain Event Payloads
# ---------------------------------------------------------------------------

class MessageAttachment(BaseModel):
    """Attachment reference within a Switch message event."""

    model_config = ConfigDict(extra="ignore")

    filename: str = Field(description="Name of the attached file")
    mimetype: str | None = Field(default=None, description="MIME type if known")
    size: int | None = Field(default=None, description="Size in bytes")
    mxc: str | None = Field(default=None, description="Media pointer identifier")
    msgtype: str | None = Field(default=None, description="Message type indicator")


class MessagePayload(BaseModel):
    """Payload for 'message' domain events."""

    model_config = ConfigDict(extra="ignore")

    addressed: bool = Field(default=False, description="Whether this message directly addressed the agent")
    sender: str = Field(default="", description="Participant ID of the sender (@localpart:server)")
    sender_name: str = Field(default="", description="Human-readable display name of the sender")
    message_id: str | None = Field(default=None, description="Unique ID of the message")
    body: str = Field(default="", description="Text content of the message")
    timestamp: int | None = Field(default=None, description="Timestamp in milliseconds")
    thread_id: str | None = Field(default=None, description="Nullable thread root ID")
    attachments: list[MessageAttachment] = Field(default_factory=list, description="Attached media references")


class CommandPayload(BaseModel):
    """Payload for 'command' domain events."""

    model_config = ConfigDict(extra="ignore")

    command: str = Field(description="Command name")
    args: str = Field(default="", description="Command arguments")
    user_id: str = Field(default="", description="Issuing user ID")
    user_name: str = Field(default="", description="Issuing user display name")
    thread_id: str | None = Field(default=None, description="Nullable thread root ID")


class RoomJoinPayload(BaseModel):
    """Payload for 'room_join' domain events."""

    model_config = ConfigDict(extra="ignore")

    member: str = Field(description="Joining member participant ID")
    member_name: str = Field(default="", description="Display name of the joining member")
    timestamp: int | None = Field(default=None, description="Timestamp in milliseconds")
    listening: bool = Field(default=True, description="Whether member is listening to room events")


class DomainEventData(BaseModel):
    """Inner 'data' payload of a Switch domain event."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["message", "command", "room_join"] | str = Field(description="Type of domain event")
    room_id: str = Field(description="ID of the room where event occurred")
    bridge_id: str | None = Field(default=None, description="Originating bridge ID if applicable")
    channel_type: str | None = Field(default=None, description="Channel classification (e.g. channel_public)")
    payload: MessagePayload | CommandPayload | RoomJoinPayload | dict[str, Any] = Field(
        description="Structured event payload"
    )
    sequence: int = Field(description="Monotonic sequence number assigned to the event")


class DomainEventFrame(BaseModel):
    """Outer frame envelope for Switch domain events."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["message", "command", "room_join"] | str = Field(description="Event name")
    data: DomainEventData = Field(description="Domain event data payload")
    id: int = Field(description="Sequence number, matching data.sequence")


# ---------------------------------------------------------------------------
# Control Frames
# ---------------------------------------------------------------------------

class ConnectionStateFrame(BaseModel):
    """Initial control frame delivered immediately upon WebSocket establishment."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["connection_state"] | None = Field(default="connection_state")
    type: Literal["connection_state"] | None = Field(default="connection_state")
    connection_id: str = Field(description="Unique connection UUID")
    agent_id: str = Field(description="Registered ID of the connecting agent")
    generation: int | str | None = Field(default=None, description="Connection generation fence token")
    scope: str = Field(default="single", description="Scope of the connection (single or all)")
    filter: str = Field(default="all", description="Delivery filter mode (all or addressed)")
    spawn_capable: bool = Field(default=False, description="Whether client supports on-demand sessions")
    rooms: list[str] = Field(default_factory=list, description="Currently covered room IDs")
    cursor: int | None = Field(default=None, description="Initial reading cursor sequence")
    protocol: int | None = Field(default=None, description="Negotiated protocol revision")
    heartbeat_interval_seconds: float = Field(default=2.0, description="Ping interval in seconds")
    server: dict[str, Any] | None = Field(default=None, description="Server metadata")
    client: dict[str, Any] | None = Field(default=None, description="Echoed client metadata")


class PingFrame(BaseModel):
    """Server-to-client heartbeat probe emitted every 2 seconds."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["ping"] | None = Field(default="ping")
    event: Literal["ping"] | None = Field(default="ping")


class PongFrame(BaseModel):
    """Client-to-server heartbeat acknowledgement carrying the highest processed sequence."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["pong"] = Field(default="pong")
    cursor: int = Field(description="Highest processed sequence number")


class GapFrame(BaseModel):
    """Server notification indicating event buffer truncation past client cursor."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["gap"] | None = Field(default="gap")
    type: Literal["gap"] | None = Field(default="gap")
    from_sequence: int = Field(description="Sequence where gap begins")
    resumed_at: int = Field(description="Sequence where delivery resumes")
    resumed_position: int | None = Field(default=None, description="Position within room log")
    rooms: list[str] = Field(default_factory=list, description="Affected room IDs")
    all_rooms: bool = Field(default=False, description="Whether all agent rooms were affected")
    reason: str | None = Field(default=None, description="Explanation for the gap")


class EvictedFrame(BaseModel):
    """Server notification indicating disconnection and whether reconnection is permitted."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["evicted"] | None = Field(default="evicted")
    type: Literal["evicted"] | None = Field(default="evicted")
    code: str = Field(description="Eviction reason code (taken_over, heartbeat_lapsed, closed, etc.)")
    reason: str | None = Field(default=None, description="Human-readable eviction reason")

    @property
    def is_terminal(self) -> bool:
        """Return True if the client MUST NOT reconnect (e.g. taken over by another instance)."""
        return self.code in ("taken_over", "closed")


class SubscriptionChangedFrame(BaseModel):
    """Server notification that room coverage has changed."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["subscription_changed"] | None = Field(default="subscription_changed")
    type: Literal["subscription_changed"] | None = Field(default="subscription_changed")
    rooms: list[str] = Field(default_factory=list, description="Updated list of covered room IDs")
    reason: str | None = Field(default=None, description="Reason for subscription change")


class RefusedFrame(BaseModel):
    """Server notification that connection was refused before socket close."""

    model_config = ConfigDict(extra="ignore")

    event: Literal["refused"] | None = Field(default="refused")
    type: Literal["refused"] | None = Field(default="refused")
    status: int = Field(description="HTTP-style status code (e.g. 409)")
    detail: str | None = Field(default=None, description="Refusal reason detail")


SwitchFrame = Annotated[
    Union[
        DomainEventFrame,
        ConnectionStateFrame,
        PingFrame,
        PongFrame,
        GapFrame,
        EvictedFrame,
        SubscriptionChangedFrame,
        RefusedFrame,
    ],
    Field(discriminator=None),
]


# ---------------------------------------------------------------------------
# Parser and Factory Utilities
# ---------------------------------------------------------------------------

def parse_switch_frame(raw_data: str | bytes | dict[str, Any]) -> SwitchFrame:
    """Parse a raw WebSocket text/binary frame or dictionary into a typed Switch frame.

    Raises:
        SwitchProtocolError: If payload is not valid JSON or does not conform to any Switch frame.
    """
    if isinstance(raw_data, (str, bytes)):
        try:
            data = json.loads(raw_data)
        except Exception as err:
            raise SwitchProtocolError(f"Malformed JSON frame: {err}") from err
    elif isinstance(raw_data, dict):
        data = raw_data
    else:
        raise SwitchProtocolError(f"Unsupported frame type: {type(raw_data).__name__}")

    if not isinstance(data, dict):
        raise SwitchProtocolError("Frame payload must be a JSON object")

    event_tag = data.get("event")
    type_tag = data.get("type")
    tag = event_tag or type_tag

    # 1. Domain Event
    if event_tag in ("message", "command", "room_join") and "data" in data and "id" in data:
        try:
            inner_data = data["data"]
            inner_type = inner_data.get("type", event_tag)
            inner_payload = inner_data.get("payload", {})

            # Parse specialized inner payloads
            if inner_type == "message" and isinstance(inner_payload, dict):
                inner_data["payload"] = MessagePayload.model_validate(inner_payload)
            elif inner_type == "command" and isinstance(inner_payload, dict):
                inner_data["payload"] = CommandPayload.model_validate(inner_payload)
            elif inner_type == "room_join" and isinstance(inner_payload, dict):
                inner_data["payload"] = RoomJoinPayload.model_validate(inner_payload)

            return DomainEventFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid domain event frame: {err}") from err

    # 2. Control Frames
    if tag == "ping":
        return PingFrame.model_validate(data)
    if tag == "pong":
        return PongFrame.model_validate(data)
    if tag == "connection_state":
        try:
            return ConnectionStateFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid connection_state frame: {err}") from err
    if tag == "gap":
        try:
            return GapFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid gap frame: {err}") from err
    if tag == "evicted":
        try:
            return EvictedFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid evicted frame: {err}") from err
    if tag == "subscription_changed":
        try:
            return SubscriptionChangedFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid subscription_changed frame: {err}") from err
    if tag == "refused":
        try:
            return RefusedFrame.model_validate(data)
        except ValidationError as err:
            raise SwitchProtocolError(f"Invalid refused frame: {err}") from err

    raise SwitchProtocolError(f"Unknown or unrecognized Switch frame kind: tag='{tag}'")


def create_pong_frame(cursor: int) -> dict[str, Any]:
    """Create a verified pong frame dictionary with the specified cursor."""
    return PongFrame(cursor=cursor).model_dump()
