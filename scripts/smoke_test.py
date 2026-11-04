"""Automated End-to-End Pipeline Smoke Test for OpenSource Guardian.

Validates the full integration pipeline across stages:
1. Configuration Validation
2. Local Service Health Check
3. GitHub Read-Only API Client Probe
4. Switch Agent Bridge REST Operation Probe
5. Event Dispatcher & PR Review Generation
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path for direct script execution
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
from src.guardian.adapters.github_client import GitHubClient, GitHubError
from src.guardian.adapters.switch_client import SwitchClientError, SwitchRestClient
from src.guardian.adapters.switch_dispatcher import SwitchEventDispatcher
from src.guardian.adapters.switch_protocol import DomainEventData, DomainEventFrame, MessagePayload
from src.guardian.config import Settings, get_settings
from src.guardian.main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("guardian.smoke_test")


class SmokeTestRunner:
    """Orchestrates sequential validation of OpenSource Guardian pipeline stages."""

    def __init__(
        self,
        repo: str | None = None,
        pr_number: int = 1,
        room_id: str = "smoke-test-room",
        mock_mode: bool = False,
    ) -> None:
        self.settings: Settings = get_settings()
        self.repo_full = repo or self.settings.default_repo or "aadesh-2006/OpenSource-Guardian"
        parts = self.repo_full.split("/")
        self.owner = parts[0] if len(parts) == 2 else "aadesh-2006"
        self.repo = parts[1] if len(parts) == 2 else "OpenSource-Guardian"
        self.pr_number = pr_number
        self.room_id = room_id
        self.mock_mode = mock_mode
        self.results: dict[str, bool] = {}

    def log_stage(self, stage_num: int, name: str, success: bool, detail: str = "") -> None:
        """Print clear progress indicator for each pipeline stage."""
        mark = "PASS" if success else "FAIL"
        detail_msg = f" - {detail}" if detail else ""
        print(f"[{stage_num}/5] [{mark}] | {name}{detail_msg}")
        self.results[name] = success

    async def stage1_validate_configuration(self) -> bool:
        """Stage 1: Verify presence of configuration without exposing secret values."""
        has_switch_url = bool(self.settings.switch_api_url)
        has_agent_id = bool(self.settings.switch_agent_id)
        has_switch_key = bool(self.settings.switch_api_key and self.settings.switch_api_key.get_secret_value())
        has_github_token = bool(self.settings.github_token and self.settings.github_token.get_secret_value())

        print("\n--- STAGE 1: Configuration Inspection ---")
        print(f"  SWITCH_API_URL:       {'Present' if has_switch_url else 'Missing'}")
        print(f"  SWITCH_AGENT_ID:      {'Present' if has_agent_id else 'Missing'}")
        print(f"  SWITCH_API_KEY:       {'Present (Masked)' if has_switch_key else 'Missing'}")
        print(f"  GITHUB_TOKEN:         {'Present (Masked)' if has_github_token else 'Missing (Public mode)'}")
        print(f"  DEFAULT_REPO:         {self.repo_full}")
        print(f"  TEST_ROOM_ID:         {self.room_id}")

        if not self.mock_mode and (not has_agent_id or not has_switch_key):
            self.log_stage(1, "Configuration Validation", False, "Missing SWITCH_AGENT_ID or SWITCH_API_KEY for live mode.")
            return False

        self.log_stage(1, "Configuration Validation", True, "Configuration verified safely.")
        return True

    async def stage2_local_service_health(self) -> bool:
        """Stage 2: Verify local FastAPI application factory and /health endpoint."""
        print("\n--- STAGE 2: Local Service Health Check ---")
        try:
            app = create_app(self.settings)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                res = await client.get("/health")
                if res.status_code == 200 and res.json().get("status") == "healthy":
                    self.log_stage(2, "Service Health", True, f"HTTP 200 OK (app: {res.json().get('app')})")
                    return True
                self.log_stage(2, "Service Health", False, f"Unexpected response: {res.status_code}")
                return False
        except Exception as err:
            self.log_stage(2, "Service Health", False, f"Health check failed: {err}")
            return False

    async def stage3_github_client_probe(self) -> bool:
        """Stage 3: Verify read-only GitHub API connectivity and repository metadata retrieval."""
        print("\n--- STAGE 3: GitHub Read-Only API Client Probe ---")
        if self.mock_mode:
            self.log_stage(3, "GitHub Read API", True, f"Mocked probe: repo '{self.owner}/{self.repo}' verified.")
            return True

        async with GitHubClient() as gh_client:
            try:
                meta = await gh_client.get_repository(self.owner, self.repo)
                self.log_stage(
                    3,
                    "GitHub Read API",
                    True,
                    f"Retrieved '{meta.full_name}' (default_branch: {meta.default_branch}, lang: {meta.language})",
                )
                return True
            except GitHubError as err:
                self.log_stage(3, "GitHub Read API", False, f"GitHub probe error: {err}")
                return False

    async def stage4_switch_bridge_probe(self) -> bool:
        """Stage 4: Probe Switch Agent Bridge REST operations."""
        print("\n--- STAGE 4: Switch Agent Bridge REST Probe ---")
        if self.mock_mode:
            self.log_stage(4, "Switch REST Bridge", True, "Mocked probe: simulated successful post_message.")
            return True

        async with SwitchRestClient(
            base_url=self.settings.switch_api_url,
            agent_id=self.settings.switch_agent_id,
            api_key=self.settings.switch_api_key,
        ) as sw_client:
            try:
                # Post controlled diagnostic smoke message
                ack = await sw_client.post_message(
                    room_id=self.room_id,
                    content="🧪 *OpenSource Guardian Automated Smoke Test Probe — Pipeline Live Check*",
                )
                self.log_stage(4, "Switch REST Bridge", True, f"Message posted successfully to room '{self.room_id}'.")
                return True
            except SwitchClientError as err:
                self.log_stage(4, "Switch REST Bridge", False, f"Switch operation failed: {err}")
                return False

    async def stage5_event_dispatch_and_review(self) -> bool:
        """Stage 5: Test complete event parsing, dispatching, and PR review generation."""
        print("\n--- STAGE 5: Event Dispatch & Review Pipeline ---")
        posted_responses: list[dict[str, Any]] = []

        class DiagnosticSwitchClient(SwitchRestClient):
            async def post_message(self, room_id: str, content: str, thread_id: str | None = None) -> dict[str, Any]:
                posted_responses.append({"room_id": room_id, "content": content, "thread_id": thread_id})
                return {"status": "ok", "room_id": room_id}

        diag_switch = DiagnosticSwitchClient(agent_id=self.settings.switch_agent_id or "test-agent")

        if self.mock_mode:
            # Synthetic mock transport for GitHub diff
            mock_diff = """diff --git a/src/smoke.py b/src/smoke.py
new file mode 100644
--- /dev/null
+++ b/src/smoke.py
@@ -0,0 +1,5 @@
+def test_pipeline():
+    return True
+"""
            mock_pr = {
                "number": self.pr_number,
                "title": "Smoke test PR verification",
                "state": "open",
                "html_url": f"https://github.com/{self.owner}/{self.repo}/pull/{self.pr_number}",
                "user": {"login": "smoke-tester"},
                "base": {"ref": "main"},
                "head": {"ref": "smoke-branch"},
                "additions": 5,
                "deletions": 0,
                "changed_files": 1,
                "body": "Smoke test diff.",
            }

            def gh_handler(request: httpx.Request) -> httpx.Response:
                if request.headers.get("Accept") == "application/vnd.github.v3.diff":
                    return httpx.Response(200, text=mock_diff)
                return httpx.Response(200, json=mock_pr)

            async with httpx.AsyncClient(transport=httpx.MockTransport(gh_handler)) as http_client:
                gh_client = GitHubClient(client=http_client)
                dispatcher = SwitchEventDispatcher(
                    switch_client=diag_switch,
                    github_client=gh_client,
                    default_repo=self.repo_full,
                )

                test_thread = "smoke-thread-101"
                frame = DomainEventFrame(
                    event="message",
                    data=DomainEventData(
                        type="message",
                        room_id=self.room_id,
                        payload=MessagePayload(
                            addressed=True,
                            sender="@smoke-user:deploy",
                            sender_name="SmokeTester",
                            body=f"@guardian review PR #{self.pr_number}",
                            thread_id=test_thread,
                        ),
                        sequence=9999,
                    ),
                    id=9999,
                )

                await dispatcher.dispatch_event(frame)

                if not posted_responses:
                    self.log_stage(5, "Event Dispatch & Review", False, "No response posted by dispatcher.")
                    return False

                reply = posted_responses[0]["content"]
                if "PR Guardian Review" in reply:
                    self.log_stage(5, "Event Dispatch & Review", True, "PR review generated and routed in thread.")
                    return True
                self.log_stage(5, "Event Dispatch & Review", False, f"Unexpected review output: {reply[:100]}")
                return False

        else:
            # Live dispatch check using configured GitHub client
            async with GitHubClient() as gh_client:
                dispatcher = SwitchEventDispatcher(
                    switch_client=diag_switch,
                    github_client=gh_client,
                    default_repo=self.repo_full,
                )

                test_thread = "live-smoke-thread-01"
                frame = DomainEventFrame(
                    event="message",
                    data=DomainEventData(
                        type="message",
                        room_id=self.room_id,
                        payload=MessagePayload(
                            addressed=True,
                            sender="@smoke-maintainer:deploy",
                            sender_name="Maintainer",
                            body=f"@guardian review PR #{self.pr_number}",
                            thread_id=test_thread,
                        ),
                        sequence=9999,
                    ),
                    id=9999,
                )

                try:
                    await dispatcher.dispatch_event(frame)
                    if posted_responses and "PR Guardian Review" in posted_responses[0]["content"]:
                        self.log_stage(5, "Event Dispatch & Review", True, "Live review completed successfully.")
                        return True
                    self.log_stage(5, "Event Dispatch & Review", False, "Review output not generated.")
                    return False
                except Exception as err:
                    self.log_stage(5, "Event Dispatch & Review", False, f"Review execution error: {err}")
                    return False

    async def run(self) -> int:
        """Execute all smoke test stages and return process exit code."""
        print("=" * 65)
        mode_label = "MOCK / CONTRACT-DRY-RUN" if self.mock_mode else "LIVE INTEGRATION"
        print(f"OPENSOURCE GUARDIAN -- PIPELINE SMOKE TEST ({mode_label})")
        print("=" * 65)

        s1 = await self.stage1_validate_configuration()
        if not s1:
            print("\n[FAIL] Smoke test aborted: Missing required credentials for live mode.")
            print("Tip: Use '--mock' or '--dry-run' to validate the full pipeline against contract fixtures.")
            return 2

        s2 = await self.stage2_local_service_health()
        s3 = await self.stage3_github_client_probe()
        s4 = await self.stage4_switch_bridge_probe()
        s5 = await self.stage5_event_dispatch_and_review()

        print("\n" + "=" * 65)
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        print(f"SUMMARY: {passed}/{total} stages passed.")
        print("=" * 65)

        return 0 if all(self.results.values()) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenSource Guardian Pipeline Smoke Test")
    parser.add_argument("--repo", type=str, default=None, help="Target repository (owner/repo)")
    parser.add_argument("--pr", type=int, default=1, help="Pull request number to evaluate")
    parser.add_argument("--room", type=str, default="smoke-test-room", help="Switch room ID for testing")
    parser.add_argument(
        "--mock",
        "--dry-run",
        dest="mock_mode",
        action="store_true",
        help="Run smoke test against contract-grounded mocks (offline / CI safe)",
    )

    args = parser.parse_args()
    runner = SmokeTestRunner(
        repo=args.repo,
        pr_number=args.pr,
        room_id=args.room,
        mock_mode=args.mock_mode,
    )
    exit_code = asyncio.run(runner.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
