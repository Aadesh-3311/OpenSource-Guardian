"""Tests for the health check endpoint and application initialization."""

import pytest
from fastapi.testclient import TestClient
from src.guardian import __version__
from src.guardian.config.settings import Settings
from src.guardian.main import app, create_app


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a TestClient for the default application."""
    return TestClient(app)


def test_health_endpoint_success(client: TestClient) -> None:
    """Ensure GET /health returns HTTP 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "OpenSource Guardian"
    assert data["version"] == __version__
    assert "environment" in data


def test_custom_settings_app_factory() -> None:
    """Verify application factory respects custom settings without external dependencies."""
    custom_settings = Settings(
        app_name="Test Guardian",
        environment="testing",
        log_level="DEBUG",
    )
    custom_app = create_app(custom_settings)
    custom_client = TestClient(custom_app)

    response = custom_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "Test Guardian"
    assert data["environment"] == "testing"


def test_settings_secret_masking() -> None:
    """Verify secrets are masked in representation and not exposed in safe summary."""
    settings = Settings(api_secret_key="super-secret-token")  # type: ignore[arg-type]
    repr_str = repr(settings)
    assert "super-secret-token" not in repr_str

    summary = settings.safe_summary()
    assert "api_secret_key" not in summary
