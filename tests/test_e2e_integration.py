"""End-to-End integration tests for OpenSource Guardian.

Validates the full pipeline:
Discord -> Switch Discord Bridge -> Switch Room -> OpenSource Guardian -> GitHub API -> Discord reply.
Also validates multi-agent collaboration and thread context follow-ups.
"""

import json
import pytest
import httpx
from src.guardian.adapters.github_client import GitHubClient
from src.guardian.adapters.switch_client import SwitchRestClient
from src.guardian.adapters.switch_dispatcher import SwitchEventDispatcher
from src.guardian.adapters.switch_protocol import (
    DomainEventData,
    DomainEventFrame,
    MessagePayload,
)
from src.guardian.modules.issue_finder import IssueFinder
from src.guardian.modules.onboarding import RepoOnboarder
from src.guardian.modules.pr_reviewer import PRReviewer


# ---------------------------------------------------------------------------
# E2E Test Fixtures & Simulators
# ---------------------------------------------------------------------------

SAMPLE_RAW_DIFF = """diff --git a/src/service.py b/src/service.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/src/service.py
@@ -0,0 +1,8 @@
+class CorePaymentService:
+    def __init__(self, api_endpoint: str):
+        self.api_endpoint = api_endpoint
+
+    def process(self, amount: int) -> bool:
+        if amount <= 0:
+            return False
+        return True
diff --git a/tests/test_service.py b/tests/test_service.py
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/tests/test_service.py
@@ -0,0 +1,6 @@
+from src.service import CorePaymentService
+
+def test_payment_processing():
+    svc = CorePaymentService("https://api.example.com")
+    assert svc.process(100) is True
+    assert svc.process(-5) is False
+"""

SAMPLE_PR_JSON = {
    "number": 42,
    "title": "Add payment processing core",
    "state": "open",
    "html_url": "https://github.com/acme/fintech/pull/42",
    "user": {"login": "amara_dev"},
    "base": {"ref": "main"},
    "head": {"ref": "amara-patch-1"},
    "additions": 21,
    "deletions": 0,
    "changed_files": 2,
    "body": "Initial implementation of payment service with unit tests.",
}

SAMPLE_ISSUES_JSON = [
    {
        "number": 15,
        "title": "Improve README setup instructions for Windows",
        "html_url": "https://github.com/acme/fintech/issues/15",
        "user": {"login": "maintainer_dan"},
        "state": "open",
        "comments": 2,
        "created_at": "2026-11-01T12:00:00Z",
        "body": "We need clearer setup steps for developers running on Windows 11 with PowerShell.",
        "labels": [{"name": "good first issue"}, {"name": "documentation"}],
    },
    {
        "number": 19,
        "title": "Add type annotations to payment utilities",
        "html_url": "https://github.com/acme/fintech/issues/19",
        "user": {"login": "maintainer_dan"},
        "state": "open",
        "comments": 0,
        "created_at": "2026-11-02T10:00:00Z",
        "body": "Payment utilities in src/utils.py lack complete type hints.",
        "labels": [{"name": "good first issue"}, {"name": "python"}],
    },
]


class EndToEndEcosystem:
    """Simulates the Switch Agent Bridge and GitHub API services."""

    def __init__(self) -> None:
        self.posted_messages: list[dict[str, Any]] = []

    def github_handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/fintech/pulls/42":
            if request.headers.get("Accept") == "application/vnd.github.v3.diff":
                return httpx.Response(200, text=SAMPLE_RAW_DIFF)
            return httpx.Response(200, json=SAMPLE_PR_JSON)

        if path == "/repos/acme/fintech/issues":
            return httpx.Response(200, json=SAMPLE_ISSUES_JSON)

        if path == "/repos/acme/fintech":
            return httpx.Response(
                200,
                json={
                    "name": "fintech",
                    "full_name": "acme/fintech",
                    "description": "Secure collaborative fintech platform",
                    "default_branch": "main",
                    "language": "Python",
                },
            )

        if path == "/repos/acme/fintech/contents/README.md":
            import base64
            readme_text = "# Acme Fintech\nSecure open platform for developer payments."
            encoded = base64.b64encode(readme_text.encode("utf-8")).decode("utf-8")
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "encoding": "base64",
                    "content": encoded,
                },
            )

        if path == "/repos/acme/fintech/pulls/999":
            return httpx.Response(404, json={"message": "Not Found"})

        return httpx.Response(404, json={"message": f"Endpoint {path} not mapped in mock"})

    def switch_handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/agents/switch-agent-guardian/ops/post_message":
            body = json.loads(request.read())
            self.posted_messages.append(body)
            return httpx.Response(200, json={"result": {"status": "posted", "id": "msg-ack"}})

        if path == "/agents/switch-agent-guardian/ops/connect_to_room":
            return httpx.Response(200, json={"result": {"status": "connected"}})

        return httpx.Response(404, json={"message": f"Switch route {path} not found"})


# ---------------------------------------------------------------------------
# E2E Workflows
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_e2e_contributor_pr_review_workflow() -> None:
    """Full workflow: Contributor asks in Discord thread -> Switch -> Guardian -> GitHub -> Discord reply."""
    ecosystem = EndToEndEcosystem()

    github_transport = httpx.MockTransport(ecosystem.github_handler)
    switch_transport = httpx.MockTransport(ecosystem.switch_handler)

    async with httpx.AsyncClient(transport=github_transport) as gh_http, \
               httpx.AsyncClient(transport=switch_transport) as sw_http:

        github_client = GitHubClient(client=gh_http)
        switch_client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="switch-agent-guardian",
            api_key="secret-key",
            client=sw_http,
        )

        dispatcher = SwitchEventDispatcher(
            switch_client=switch_client,
            github_client=github_client,
            default_repo="acme/fintech",
        )

        # Discord message event bridged into Switch
        event_frame = DomainEventFrame(
            event="message",
            data=DomainEventData(
                type="message",
                room_id="room-discord-contributions",
                channel_type="channel_public",
                payload=MessagePayload(
                    addressed=True,
                    sender="@switch-user-amara:deploy",
                    sender_name="Amara",
                    message_id="discord-msg-101",
                    body="@guardian review PR #42",
                    thread_id="discord-pr-42-thread",
                ),
                sequence=1001,
            ),
            id=1001,
        )

        await dispatcher.dispatch_event(event_frame)

        # Verify posted response in Switch / Discord
        assert len(ecosystem.posted_messages) == 1
        posted = ecosystem.posted_messages[0]
        assert posted["room_id"] == "room-discord-contributions"
        assert posted["thread_id"] == "discord-pr-42-thread"

        content = posted["content"]
        assert "🛡️ PR Guardian Review" in content
        assert "Add payment processing core" in content
        assert "@amara_dev" in content
        assert "Automated test updates included" in content
        assert "Review Disclaimer" in content


@pytest.mark.anyio
async def test_e2e_contributor_issue_discovery_workflow() -> None:
    """Full workflow: Contributor asks for beginner issues in Discord -> Guardian returns curated list."""
    ecosystem = EndToEndEcosystem()

    github_transport = httpx.MockTransport(ecosystem.github_handler)
    switch_transport = httpx.MockTransport(ecosystem.switch_handler)

    async with httpx.AsyncClient(transport=github_transport) as gh_http, \
               httpx.AsyncClient(transport=switch_transport) as sw_http:

        github_client = GitHubClient(client=gh_http)
        switch_client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="switch-agent-guardian",
            client=sw_http,
        )

        dispatcher = SwitchEventDispatcher(
            switch_client=switch_client,
            github_client=github_client,
            default_repo="acme/fintech",
        )

        event_frame = DomainEventFrame(
            event="message",
            data=DomainEventData(
                type="message",
                room_id="room-discord-welcome",
                payload=MessagePayload(
                    addressed=True,
                    sender="@switch-user-newcomer:deploy",
                    sender_name="NewContributor",
                    body="@guardian find good first issues in python",
                    thread_id="welcome-thread",
                ),
                sequence=1002,
            ),
            id=1002,
        )

        await dispatcher.dispatch_event(event_frame)

        assert len(ecosystem.posted_messages) == 1
        posted = ecosystem.posted_messages[0]
        assert posted["room_id"] == "room-discord-welcome"
        assert posted["thread_id"] == "welcome-thread"

        content = posted["content"]
        assert "🎯 Good First Issues for `acme/fintech`" in content
        assert "Add type annotations to payment utilities" in content
        assert "https://github.com/acme/fintech/issues/19" in content


@pytest.mark.anyio
async def test_e2e_maintainer_followups_in_same_thread() -> None:
    """Full workflow: PR review followed by maintainer questions in the same thread."""
    ecosystem = EndToEndEcosystem()

    github_transport = httpx.MockTransport(ecosystem.github_handler)
    switch_transport = httpx.MockTransport(ecosystem.switch_handler)

    async with httpx.AsyncClient(transport=github_transport) as gh_http, \
               httpx.AsyncClient(transport=switch_transport) as sw_http:

        github_client = GitHubClient(client=gh_http)
        switch_client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="switch-agent-guardian",
            client=sw_http,
        )

        dispatcher = SwitchEventDispatcher(
            switch_client=switch_client,
            github_client=github_client,
            default_repo="acme/fintech",
        )

        thread_id = "discord-thread-42"

        # 1. Initial Review
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id="room-triage",
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-user-amara:deploy",
                        body="@guardian review PR #42",
                        thread_id=thread_id,
                    ),
                    sequence=2001,
                ),
                id=2001,
            )
        )
        assert len(ecosystem.posted_messages) == 1

        # 2. Maintainer asks: "@guardian what tests are missing?"
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id="room-triage",
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-user-luis:deploy",
                        sender_name="Luis (Maintainer)",
                        body="@guardian what tests are missing?",
                        thread_id=thread_id,
                    ),
                    sequence=2002,
                ),
                id=2002,
            )
        )
        assert len(ecosystem.posted_messages) == 2
        reply_test = ecosystem.posted_messages[1]["content"]
        assert "Test Status for PR #42" in reply_test
        assert "Test Coverage Looks Good" in reply_test  # PR #42 included test_service.py

        # 3. Maintainer asks: "@guardian is this secure?"
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id="room-triage",
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-user-luis:deploy",
                        sender_name="Luis (Maintainer)",
                        body="@guardian is there any secret or security issue?",
                        thread_id=thread_id,
                    ),
                    sequence=2003,
                ),
                id=2003,
            )
        )
        assert len(ecosystem.posted_messages) == 3
        reply_sec = ecosystem.posted_messages[2]["content"]
        assert "Security Status for PR #42" in reply_sec
        assert "No Security Secrets Detected" in reply_sec

        # 4. Contributor re-checks after discussion: "@guardian review again"
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id="room-triage",
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-user-amara:deploy",
                        sender_name="Amara",
                        body="@guardian review again",
                        thread_id=thread_id,
                    ),
                    sequence=2004,
                ),
                id=2004,
            )
        )
        assert len(ecosystem.posted_messages) == 4
        assert "🛡️ PR Guardian Review" in ecosystem.posted_messages[3]["content"]


@pytest.mark.anyio
async def test_e2e_multi_agent_collaboration_and_loop_prevention() -> None:
    """Verify room collaboration with human maintainer + contributor agent + Guardian without infinite loops."""
    ecosystem = EndToEndEcosystem()

    github_transport = httpx.MockTransport(ecosystem.github_handler)
    switch_transport = httpx.MockTransport(ecosystem.switch_handler)

    async with httpx.AsyncClient(transport=github_transport) as gh_http, \
               httpx.AsyncClient(transport=switch_transport) as sw_http:

        github_client = GitHubClient(client=gh_http)
        switch_client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="switch-agent-guardian",
            client=sw_http,
        )

        dispatcher = SwitchEventDispatcher(
            switch_client=switch_client,
            github_client=github_client,
            default_repo="acme/fintech",
        )

        room_id = "room-multiagent-contributions"
        thread_id = "thread-pr-42"

        # 1. Contributor agent (amara-agent) requests review from Guardian
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id=room_id,
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-agent-amara:deploy",
                        sender_name="amara-agent",
                        body="@guardian review PR #42",
                        thread_id=thread_id,
                    ),
                    sequence=3001,
                ),
                id=3001,
            )
        )
        assert len(ecosystem.posted_messages) == 1
        assert "🛡️ PR Guardian Review" in ecosystem.posted_messages[0]["content"]

        # 2. amara-agent addresses maintainer Luis (not Guardian)
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id=room_id,
                    payload=MessagePayload(
                        addressed=False,
                        sender="@switch-agent-amara:deploy",
                        sender_name="amara-agent",
                        body="@Luis I addressed the connection timeout in this PR.",
                        thread_id=thread_id,
                    ),
                    sequence=3002,
                ),
                id=3002,
            )
        )
        # Guardian must NOT reply to conversations between other participants
        assert len(ecosystem.posted_messages) == 1

        # 3. Luis replies to amara-agent (not Guardian)
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id=room_id,
                    payload=MessagePayload(
                        addressed=False,
                        sender="@switch-user-luis:deploy",
                        sender_name="Luis",
                        body="@amara-agent looks good, verifying test suite now.",
                        thread_id=thread_id,
                    ),
                    sequence=3003,
                ),
                id=3003,
            )
        )
        assert len(ecosystem.posted_messages) == 1

        # 4. Message from Guardian's own agent ID or sender name (self-message loop protection)
        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id=room_id,
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-agent-guardian:deploy",
                        sender_name="OpenSource Guardian",
                        body="@guardian review PR #42",
                        thread_id=thread_id,
                    ),
                    sequence=3004,
                ),
                id=3004,
            )
        )
        # Zero response to self
        assert len(ecosystem.posted_messages) == 1


@pytest.mark.anyio
async def test_e2e_resilience_not_found_handling() -> None:
    """Verify graceful handling when a non-existent PR is requested."""
    ecosystem = EndToEndEcosystem()

    github_transport = httpx.MockTransport(ecosystem.github_handler)
    switch_transport = httpx.MockTransport(ecosystem.switch_handler)

    async with httpx.AsyncClient(transport=github_transport) as gh_http, \
               httpx.AsyncClient(transport=switch_transport) as sw_http:

        github_client = GitHubClient(client=gh_http)
        switch_client = SwitchRestClient(
            base_url="http://switch-bridge:8080",
            agent_id="switch-agent-guardian",
            client=sw_http,
        )

        dispatcher = SwitchEventDispatcher(
            switch_client=switch_client,
            github_client=github_client,
            default_repo="acme/fintech",
        )

        await dispatcher.dispatch_event(
            DomainEventFrame(
                event="message",
                data=DomainEventData(
                    type="message",
                    room_id="room-triage",
                    payload=MessagePayload(
                        addressed=True,
                        sender="@switch-user-bob:deploy",
                        body="@guardian review PR #999",
                        thread_id="thread-999",
                    ),
                    sequence=4001,
                ),
                id=4001,
            )
        )

        assert len(ecosystem.posted_messages) == 1
        content = ecosystem.posted_messages[0]["content"]
        assert "🔍 **Not Found**" in content
        assert "Please verify the repository name and issue/PR number" in content
