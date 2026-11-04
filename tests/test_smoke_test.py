"""Unit tests for the automated pipeline smoke test script."""

import pytest
from scripts.smoke_test import SmokeTestRunner


@pytest.mark.anyio
async def test_smoke_test_mock_mode_execution() -> None:
    """Verify SmokeTestRunner passes all 5 stages in mock / contract-dry-run mode."""
    runner = SmokeTestRunner(
        repo="acme/test-repo",
        pr_number=1,
        room_id="test-room",
        mock_mode=True,
    )
    exit_code = await runner.run()
    assert exit_code == 0
    assert len(runner.results) == 5
    assert all(runner.results.values())


@pytest.mark.anyio
async def test_smoke_test_live_mode_missing_credentials_aborts() -> None:
    """Verify SmokeTestRunner cleanly aborts with code 2 when required live credentials are missing."""
    runner = SmokeTestRunner(
        repo="acme/test-repo",
        mock_mode=False,
    )
    # Ensure agent_id is empty to trigger configuration guard
    runner.settings.switch_agent_id = None
    exit_code = await runner.run()
    assert exit_code == 2
    assert runner.results.get("Configuration Validation") is False
