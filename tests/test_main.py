"""Tests for the application lifespan, startup, shutdown, and runner logic."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.guardian.config import Settings
from src.guardian.main import create_app


def test_lifespan_health_only_mode_when_credentials_missing() -> None:
    """Verify application runs in health-only mode when Switch credentials are absent."""
    settings = Settings(
        switch_agent_id=None,
        switch_api_key=None,
        environment="testing",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["mode"] == "health_only"
        assert test_app.state.ws_task is None
        assert test_app.state.ws_client is None


def test_lifespan_starts_websocket_listener_when_credentials_present() -> None:
    """Verify application starts WebSocket listener background task when credentials exist."""
    settings = Settings(
        switch_agent_id="test-agent-123",
        switch_api_key=SecretStr("test-secret-key"),
        switch_api_url="http://localhost:8080",
        environment="testing",
    )
    test_app = create_app(settings)

    async def fake_run_loop(*args: Any, **kwargs: Any) -> None:
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass

    with patch("src.guardian.main.SwitchWebSocketClient.run_loop", new=fake_run_loop):
        with TestClient(test_app) as client:
            res = client.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "healthy"
            assert data["mode"] == "agent"

            # Check that background task was spawned
            task = test_app.state.ws_task
            assert task is not None
            assert not task.done()
            assert test_app.state.ws_client is not None
            assert test_app.state.ws_client.agent_id == "test-agent-123"

        # After exiting the context manager, shutdown must have cancelled the task
        assert task.done()


def test_lifespan_cleans_up_on_shutdown() -> None:
    """Verify application shutdown stops client and awaits task cancellation cleanly."""
    settings = Settings(
        switch_agent_id="test-agent-123",
        switch_api_key=SecretStr("test-secret-key"),
        switch_api_url="http://localhost:8080",
        environment="testing",
    )
    test_app = create_app(settings)

    stop_called = False

    async def fake_run_loop(self: Any) -> None:
        try:
            while True:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass

    def fake_stop(self: Any) -> None:
        nonlocal stop_called
        stop_called = True

    with patch("src.guardian.main.SwitchWebSocketClient.run_loop", new=fake_run_loop), \
         patch("src.guardian.main.SwitchWebSocketClient.stop", new=fake_stop):
        with TestClient(test_app):
            task = test_app.state.ws_task
            assert task is not None
            assert not task.done()
            assert not stop_called

        # After exiting context manager
        assert stop_called is True
        assert task.done()


def test_lifespan_handles_startup_exception() -> None:
    """Verify application raises startup errors if initialization fails."""
    settings = Settings(
        switch_agent_id="test-agent-123",
        switch_api_key=SecretStr("test-secret-key"),
        switch_api_url="http://localhost:8080",
        environment="testing",
    )
    test_app = create_app(settings)

    with patch("src.guardian.main.GitHubClient", side_effect=RuntimeError("GitHub client init failed")):
        with pytest.raises(RuntimeError, match="GitHub client init failed"):
            with TestClient(test_app):
                pass


def test_health_endpoint_response_structure() -> None:
    """Verify health check endpoint returns all expected contract fields."""
    settings = Settings(environment="production")
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "healthy"
        assert payload["app"] == "OpenSource Guardian"
        assert "version" in payload
        assert payload["environment"] == "production"
        assert payload["mode"] == "health_only"
