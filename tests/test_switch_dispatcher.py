"""Unit tests for SwitchEventDispatcher and chat routing."""

import pytest
import httpx
from src.guardian.adapters.github_client import GitHubClient, GitHubNotFoundError
from src.guardian.adapters.switch_client import SwitchRestClient
from src.guardian.adapters.switch_dispatcher import SwitchEventDispatcher
from src.guardian.adapters.switch_protocol import (
    DomainEventData,
    DomainEventFrame,
    MessagePayload,
)
from src.guardian.modules.issue_finder import IssueDiscoveryReport, IssueFinder, RankedIssue
from src.guardian.modules.onboarding import OnboardingReport, RepoOnboarder
from src.guardian.modules.pr_reviewer import PRReviewReport, PRReviewer, ReviewFinding


class MockSwitchRestClient(SwitchRestClient):
    """Mock Switch client to capture posted messages."""

    def __init__(self) -> None:
        super().__init__(agent_id="guardian-agent")
        self.posted_messages: list[dict[str, str | None]] = []

    async def post_message(
        self,
        room_id: str,
        content: str,
        thread_id: str | None = None,
    ) -> dict[str, str]:
        self.posted_messages.append({"room_id": room_id, "content": content, "thread_id": thread_id})
        return {"status": "success", "room_id": room_id}


def test_is_addressed_and_mention_recognition() -> None:
    """Verify addressed flag and regex mention recognition."""
    dispatcher = SwitchEventDispatcher(
        switch_client=MockSwitchRestClient(),
        github_client=GitHubClient(),
    )

    # Flag
    assert dispatcher.is_addressed("hello", addressed_flag=True) is True
    assert dispatcher.is_addressed("hello", addressed_flag=False) is False

    # Regex mentions
    assert dispatcher.is_addressed("@guardian review PR #1") is True
    assert dispatcher.is_addressed("@OpenSource-Guardian help") is True
    assert dispatcher.is_addressed("Hey !guardian what can you do?") is True
    assert dispatcher.is_addressed("just talking to alice") is False


def test_command_parsing() -> None:
    """Verify parsing of PR review, issue discovery, onboarding, and help commands."""
    dispatcher = SwitchEventDispatcher(
        switch_client=MockSwitchRestClient(),
        github_client=GitHubClient(),
        default_repo="owner/myrepo",
    )

    # PR Review with default repo
    cmd, params = dispatcher.parse_command("@guardian review PR #42")  # type: ignore[misc]
    assert cmd == "review_pr"
    assert params["owner"] == "owner"
    assert params["repo"] == "myrepo"
    assert params["pr_number"] == 42

    # PR Review with explicit repo
    cmd, params = dispatcher.parse_command("@guardian check pr acme/tools#101")  # type: ignore[misc]
    assert cmd == "review_pr"
    assert params["owner"] == "acme"
    assert params["repo"] == "tools"
    assert params["pr_number"] == 101

    # Issue Discovery with language
    cmd, params = dispatcher.parse_command("@guardian find good first issues in python")  # type: ignore[misc]
    assert cmd == "find_issues"
    assert params["language"] == "python"

    # Onboarding
    cmd, params = dispatcher.parse_command("@guardian explain repository")  # type: ignore[misc]
    assert cmd == "onboard"

    # Help
    cmd, params = dispatcher.parse_command("@guardian what is the meaning of life?")  # type: ignore[misc]
    assert cmd == "help"


@pytest.mark.anyio
async def test_handle_message_routes_to_pr_reviewer() -> None:
    """Verify PR review command invokes PRReviewer and posts response to room."""
    mock_switch = MockSwitchRestClient()

    class MockPRReviewer(PRReviewer):
        async def review_pr(self, owner: str, repo: str, pr_number: int) -> PRReviewReport:
            return PRReviewReport(
                pr_number=pr_number,
                repo=f"{owner}/{repo}",
                formatted_markdown=f"# Review for PR #{pr_number}",
            )

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
        pr_reviewer=MockPRReviewer(github_client=GitHubClient()),
        default_repo="acme/proj",
    )

    msg = MessagePayload(
        addressed=True,
        sender="@user:server",
        sender_name="Alice",
        body="@guardian review PR #88",
        thread_id="thread-42",
    )

    reply = await dispatcher.handle_message(msg, room_id="room-1")
    assert reply == "# Review for PR #88"
    assert len(mock_switch.posted_messages) == 1
    assert mock_switch.posted_messages[0]["thread_id"] == "thread-42"
    assert mock_switch.posted_messages[0]["content"] == "# Review for PR #88"


@pytest.mark.anyio
async def test_handle_message_routes_to_issue_finder() -> None:
    """Verify issue discovery command invokes IssueFinder and posts formatted list."""
    mock_switch = MockSwitchRestClient()

    class MockIssueFinder(IssueFinder):
        async def find_good_first_issues(self, owner: str, repo: str, language: str | None = None) -> IssueDiscoveryReport:
            return IssueDiscoveryReport(
                owner=owner,
                repo=repo,
                total_found=1,
                ranked_issues=[
                    RankedIssue(
                        number=7,
                        title="Add typing annotations",
                        html_url="https://github.com/acme/proj/issues/7",
                        labels=["good first issue", "python"],
                        suitability_score=95,
                        score_reasons=["explicit beginner label", "descriptive title"],
                        created_at="2026-11-01T00:00:00Z",
                    )
                ],
            )

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
        issue_finder=MockIssueFinder(github_client=GitHubClient()),
        default_repo="acme/proj",
    )

    msg = MessagePayload(
        addressed=True,
        sender="@user:server",
        sender_name="Alice",
        body="@guardian find issues in python",
    )

    reply = await dispatcher.handle_message(msg, room_id="room-1")
    assert reply is not None
    assert "## 🎯 Good First Issues for `acme/proj`" in reply
    assert "[#7 Add typing annotations]" in reply
    assert "Signals*: explicit beginner label" in reply


@pytest.mark.anyio
async def test_handle_message_routes_to_onboarder() -> None:
    """Verify onboarding command invokes RepoOnboarder and posts formatted guide."""
    mock_switch = MockSwitchRestClient()

    class MockOnboarder(RepoOnboarder):
        async def onboard(self, owner: str, repo: str) -> OnboardingReport:
            return OnboardingReport(
                repo_name=repo,
                owner=owner,
                full_name=f"{owner}/{repo}",
                description="A stellar open source repository",
                default_branch="main",
                primary_language="Python",
                readme_summary="Project documentation summary",
                setup_instructions="Run pip install -r requirements.txt",
                contribution_guidelines="Open a PR against main",
            )

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
        onboarder=MockOnboarder(github_client=GitHubClient()),
        default_repo="acme/proj",
    )

    msg = MessagePayload(
        addressed=True,
        sender="@user:server",
        sender_name="Alice",
        body="@guardian explain repository",
    )

    reply = await dispatcher.handle_message(msg, room_id="room-1")
    assert reply is not None
    assert "## 🚀 Welcome to `acme/proj`" in reply
    assert "A stellar open source repository" in reply
    assert "Getting Started & Setup" in reply


@pytest.mark.anyio
async def test_handle_message_loop_prevention() -> None:
    """Verify Guardian ignores messages sent by itself or other Guardian instances."""
    mock_switch = MockSwitchRestClient()
    mock_switch.agent_id = "agent-guardian-id"

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
    )

    # 1. Message from matching agent ID
    msg_self = MessagePayload(
        addressed=True,
        sender="@agent-guardian-id:server",
        sender_name="SomeBot",
        body="@guardian review PR #1",
    )
    res1 = await dispatcher.handle_message(msg_self, room_id="room-1")
    assert res1 is None
    assert len(mock_switch.posted_messages) == 0

    # 2. Message from sender_name containing guardian
    msg_bot = MessagePayload(
        addressed=True,
        sender="@other:server",
        sender_name="OpenSource Guardian",
        body="@guardian review PR #1",
    )
    res2 = await dispatcher.handle_message(msg_bot, room_id="room-1")
    assert res2 is None
    assert len(mock_switch.posted_messages) == 0


@pytest.mark.anyio
async def test_handle_message_github_not_found_error() -> None:
    """Verify GitHubNotFoundError produces a polite user-facing message."""
    mock_switch = MockSwitchRestClient()

    class FailingPRReviewer(PRReviewer):
        async def review_pr(self, owner: str, repo: str, pr_number: int) -> PRReviewReport:
            raise GitHubNotFoundError(f"Pull request #{pr_number} not found in {owner}/{repo}")

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
        pr_reviewer=FailingPRReviewer(github_client=GitHubClient()),
        default_repo="acme/proj",
    )

    msg = MessagePayload(
        addressed=True,
        sender="@user:server",
        sender_name="Alice",
        body="@guardian review PR #999",
    )

    reply = await dispatcher.handle_message(msg, room_id="room-1")
    assert reply is not None
    assert "🔍 **Not Found**" in reply
    assert "Pull request #999 not found" in reply


@pytest.mark.anyio
async def test_dispatch_domain_event_frame() -> None:
    """Verify top-level dispatch_event handles DomainEventFrame."""
    mock_switch = MockSwitchRestClient()
    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
    )

    frame = DomainEventFrame(
        event="message",
        data=DomainEventData(
            type="message",
            room_id="room-test",
            payload=MessagePayload(
                addressed=True,
                sender="@user:server",
                sender_name="Bob",
                body="@guardian help",
            ),
            sequence=1001,
        ),
        id=1001,
    )

    await dispatcher.dispatch_event(frame)
    assert len(mock_switch.posted_messages) == 1
    assert "OpenSource Guardian — Available Commands" in mock_switch.posted_messages[0]["content"]


# ---------------------------------------------------------------------------
# Thread Context & Follow-up Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_thread_context_followup_workflow() -> None:
    """Verify full maintainer thread workflow: review -> follow-up question -> contextual response."""
    mock_switch = MockSwitchRestClient()

    class ReviewerWithFindings(PRReviewer):
        async def review_pr(self, owner: str, repo: str, pr_number: int) -> PRReviewReport:
            return PRReviewReport(
                pr_number=pr_number,
                repo=f"{owner}/{repo}",
                findings=[
                    ReviewFinding(
                        category="TESTING",
                        severity="WARNING",
                        message="New service module added without unit test updates.",
                        file_path="src/service.py",
                        suggestion="Add tests in tests/test_service.py to verify behavior.",
                    ),
                    ReviewFinding(
                        category="SECURITY",
                        severity="CRITICAL",
                        message="Possible hardcoded credential pattern detected.",
                        file_path="src/config.py",
                        suggestion="Store secrets in environment variables instead.",
                    ),
                ],
                positive_notes=["Focused change set under 100 lines."],
                formatted_markdown=f"# Initial Review PR #{pr_number}",
            )

    dispatcher = SwitchEventDispatcher(
        switch_client=mock_switch,
        github_client=GitHubClient(),
        pr_reviewer=ReviewerWithFindings(github_client=GitHubClient()),
        default_repo="acme/proj",
    )

    thread_id = "discord-thread-99"

    # Step 1: Initial PR Review in thread
    msg_initial = MessagePayload(
        addressed=True,
        sender="@contributor:server",
        sender_name="Amara",
        body="@guardian review PR #452",
        thread_id=thread_id,
    )
    res_initial = await dispatcher.handle_message(msg_initial, room_id="room-contributions")
    assert res_initial == "# Initial Review PR #452"
    assert thread_id in dispatcher.thread_contexts
    assert dispatcher.thread_contexts[thread_id].last_pr_number == 452

    # Step 2: Maintainer asks about testing in the same thread
    msg_test = MessagePayload(
        addressed=True,
        sender="@maintainer:server",
        sender_name="Luis",
        body="@guardian what tests are missing?",
        thread_id=thread_id,
    )
    res_test = await dispatcher.handle_message(msg_test, room_id="room-contributions")
    assert res_test is not None
    assert "Test Status for PR #452" in res_test
    assert "New service module added without unit test updates" in res_test
    assert "Add tests in tests/test_service.py" in res_test

    # Step 3: Maintainer asks about security in the same thread
    msg_sec = MessagePayload(
        addressed=True,
        sender="@maintainer:server",
        sender_name="Luis",
        body="@guardian is there any security concern?",
        thread_id=thread_id,
    )
    res_sec = await dispatcher.handle_message(msg_sec, room_id="room-contributions")
    assert res_sec is not None
    assert "Security Status for PR #452" in res_sec
    assert "Critical Security Concerns Detected" in res_sec
    assert "Store secrets in environment variables" in res_sec

    # Step 4: Maintainer asks for a summary
    msg_sum = MessagePayload(
        addressed=True,
        sender="@maintainer:server",
        sender_name="Luis",
        body="@guardian summarize findings",
        thread_id=thread_id,
    )
    res_sum = await dispatcher.handle_message(msg_sum, room_id="room-contributions")
    assert res_sum is not None
    assert "Review Summary for PR #452" in res_sum
    assert "**Total Findings**: 2 finding(s)" in res_sum
    assert "1 Critical, 1 Warning" in res_sum

    # Step 5: Contributor asks to review again without repeating PR number
    msg_rereview = MessagePayload(
        addressed=True,
        sender="@contributor:server",
        sender_name="Amara",
        body="@guardian review again",
        thread_id=thread_id,
    )
    res_rereview = await dispatcher.handle_message(msg_rereview, room_id="room-contributions")
    assert res_rereview == "# Initial Review PR #452"


def test_thread_context_max_history_eviction() -> None:
    """Verify bounded memory limits in thread context cache."""
    dispatcher = SwitchEventDispatcher(
        switch_client=MockSwitchRestClient(),
        github_client=GitHubClient(),
    )
    dispatcher.MAX_THREAD_HISTORY = 3

    for i in range(5):
        dispatcher._record_thread_context(
            thread_id=f"t-{i}",
            owner="o",
            repo="r",
            last_action="review_pr",
            last_pr_number=i,
        )

    # Oldest (t-0 and t-1) should have been evicted
    assert len(dispatcher.thread_contexts) == 3
    assert "t-0" not in dispatcher.thread_contexts
    assert "t-1" not in dispatcher.thread_contexts
    assert "t-2" in dispatcher.thread_contexts
    assert "t-4" in dispatcher.thread_contexts

