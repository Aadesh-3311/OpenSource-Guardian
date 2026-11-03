"""Unit tests for onboarding and issue discovery modules."""

import base64
import httpx
import pytest

from src.guardian.adapters.github_client import GitHubClient, GitHubNotFoundError
from src.guardian.modules.issue_finder import IssueFinder, RankedIssue
from src.guardian.modules.onboarding import OnboardingReport, RepoOnboarder


# ---------------------------------------------------------------------------
# Fixtures & Test Data
# ---------------------------------------------------------------------------

SAMPLE_METADATA = {
    "name": "sample-project",
    "full_name": "acme/sample-project",
    "description": "An open-source automation toolkit",
    "default_branch": "main",
    "fork": False,
    "stargazers_count": 150,
    "open_issues_count": 12,
    "html_url": "https://github.com/acme/sample-project",
    "language": "Python",
}

SAMPLE_README = """# Sample Project

An open-source automation toolkit designed for modern developers.

## Overview
Sample Project streamlines task scheduling and workflow pipelines.

## Installation & Setup
To install dependencies and start the app:
```bash
pip install -r requirements.txt
python main.py
```

## Features & Goals
- High-speed job execution
- Zero database requirements
- Native Docker container support

## Contributing
Please see our contributing guidelines before submitting a pull request.
"""

SAMPLE_CONTRIBUTING = """# Contributing Guidelines

Thank you for contributing!
1. Fork the repository
2. Run pytest locally
3. Open a clean pull request
"""


def encode_b64(text: str) -> str:
    """Helper to encode string to base64."""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# RepoOnboarder Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_onboard_with_readme_and_contributing() -> None:
    """Verify onboarding report when both README and CONTRIBUTING exist."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/sample-project":
            return httpx.Response(200, json=SAMPLE_METADATA)
        elif path == "/repos/acme/sample-project/contents/README.md":
            return httpx.Response(200, json={"encoding": "base64", "content": encode_b64(SAMPLE_README)})
        elif path == "/repos/acme/sample-project/contents/CONTRIBUTING.md":
            return httpx.Response(200, json={"encoding": "base64", "content": encode_b64(SAMPLE_CONTRIBUTING)})
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        onboarder = RepoOnboarder(github_client)

        report = await onboarder.onboard("acme", "sample-project")

        assert isinstance(report, OnboardingReport)
        assert report.repo_name == "sample-project"
        assert report.owner == "acme"
        assert report.primary_language == "Python"
        assert report.has_readme is True
        assert report.has_contributing is True
        assert "streamlines task scheduling" in (report.readme_summary or "")
        assert "pip install" in (report.setup_instructions or "")
        assert "Fork the repository" in (report.contribution_guidelines or "")
        assert len(report.high_level_goals) >= 2
        assert "High-speed job execution" in report.high_level_goals
        assert "Python" in report.detected_technologies
        assert "Docker" in report.detected_technologies
        assert report.is_inferred["detected_technologies"] is True


@pytest.mark.anyio
async def test_onboard_when_contributing_missing() -> None:
    """Verify fallback to README contributing section when CONTRIBUTING.md is absent."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/sample-project":
            return httpx.Response(200, json=SAMPLE_METADATA)
        elif path == "/repos/acme/sample-project/contents/README.md":
            return httpx.Response(200, json={"encoding": "base64", "content": encode_b64(SAMPLE_README)})
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        onboarder = RepoOnboarder(github_client)

        report = await onboarder.onboard("acme", "sample-project")

        assert report.has_readme is True
        assert report.has_contributing is False
        # Falling back to README's contributing section
        assert "Please see our contributing guidelines" in (report.contribution_guidelines or "")
        assert report.is_inferred["contribution_guidelines"] is True


@pytest.mark.anyio
async def test_onboard_when_both_readme_and_contributing_missing() -> None:
    """Verify graceful degradation when repository lacks both README and CONTRIBUTING."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/sample-project":
            return httpx.Response(200, json=SAMPLE_METADATA)
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        onboarder = RepoOnboarder(github_client)

        report = await onboarder.onboard("acme", "sample-project")

        assert report.has_readme is False
        assert report.has_contributing is False
        assert report.readme_summary == SAMPLE_METADATA["description"]
        assert report.setup_instructions is None
        assert report.contribution_guidelines is None
        assert report.high_level_goals == [SAMPLE_METADATA["description"]]
        assert report.is_inferred["high_level_goals"] is True


# ---------------------------------------------------------------------------
# IssueFinder Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_issue_discovery_and_deterministic_ranking() -> None:
    """Verify issue discovery ranks beginner-friendly issues higher deterministically."""
    mock_issues = [
        # Issue 1: High suitability (good first issue label, structured body with code, 0 comments)
        {
            "number": 10,
            "title": "Fix typo in docs",
            "body": "Here is the issue: `typo_here`. Can you please fix this in the README? - [ ] Update line 5",
            "state": "open",
            "html_url": "https://github.com/acme/sample-project/issues/10",
            "labels": [{"name": "good first issue"}, {"name": "documentation"}],
            "user": {"login": "maintainer1"},
            "comments": 0,
            "created_at": "2026-11-04T01:00:00Z",
        },
        # Issue 2: Medium suitability (help wanted, short body, 1 comment)
        {
            "number": 11,
            "title": "Add helper script",
            "body": "We need a helper script to run diagnostics.",
            "state": "open",
            "html_url": "https://github.com/acme/sample-project/issues/11",
            "labels": [{"name": "help wanted"}],
            "user": {"login": "maintainer1"},
            "comments": 1,
            "created_at": "2026-11-04T02:00:00Z",
        },
        # Issue 3: Low suitability (no beginner labels, long comment thread)
        {
            "number": 12,
            "title": "Architectural refactoring of core engine",
            "body": "Major refactor needed across all subsystems.",
            "state": "open",
            "html_url": "https://github.com/acme/sample-project/issues/12",
            "labels": [{"name": "architecture"}],
            "user": {"login": "architect"},
            "comments": 8,
            "created_at": "2026-11-04T00:30:00Z",
        },
        # Issue 4: A pull request (should be excluded by client)
        {
            "number": 13,
            "title": "PR: Refactor engine",
            "body": "PR content",
            "state": "open",
            "html_url": "https://github.com/acme/sample-project/pull/13",
            "pull_request": {"url": "https://api.github.com/..."},
            "labels": [{"name": "good first issue"}],
            "user": {"login": "dev"},
            "comments": 0,
            "created_at": "2026-11-04T03:00:00Z",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_issues)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        finder = IssueFinder(github_client)

        report = await finder.find_issues("acme", "sample-project", limit=5)

        assert report.total_found == 3  # PR #13 filtered out
        assert len(report.ranked_issues) == 3

        top_issue = report.ranked_issues[0]
        second_issue = report.ranked_issues[1]
        third_issue = report.ranked_issues[2]

        # Assert rank ordering
        assert top_issue.number == 10
        assert second_issue.number == 11
        assert third_issue.number == 12

        # Assert score monotonicity
        assert top_issue.suitability_score > second_issue.suitability_score
        assert second_issue.suitability_score > third_issue.suitability_score

        # Check explicit score breakdown
        assert any("good first issue" in reason for reason in top_issue.score_reasons)
        assert any("Zero comments" in reason for reason in top_issue.score_reasons)
        assert "Heuristic suitability scores" in report.disclaimer


@pytest.mark.anyio
async def test_issue_discovery_empty_results() -> None:
    """Verify issue discovery handles empty issues list cleanly."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        finder = IssueFinder(github_client)

        report = await finder.find_issues("acme", "empty-project")

        assert report.total_found == 0
        assert report.ranked_issues == []
        assert report.owner == "acme"
        assert report.repo == "empty-project"


@pytest.mark.anyio
async def test_issue_deterministic_tie_breaker() -> None:
    """Verify issues with identical scores are ordered deterministically by comments and number."""
    mock_issues = [
        {
            "number": 50,
            "title": "Issue B",
            "body": "Simple task description",
            "state": "open",
            "html_url": "https://github.com/acme/sample/issues/50",
            "labels": [{"name": "good first issue"}],
            "comments": 1,
            "created_at": "2026-11-04T00:00:00Z",
        },
        {
            "number": 20,
            "title": "Issue A",
            "body": "Simple task description",
            "state": "open",
            "html_url": "https://github.com/acme/sample/issues/20",
            "labels": [{"name": "good first issue"}],
            "comments": 1,
            "created_at": "2026-11-04T00:00:00Z",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_issues)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        finder = IssueFinder(github_client)

        report = await finder.find_issues("acme", "sample")
        assert len(report.ranked_issues) == 2
        # Identical scores and comments -> ordered by issue number ascending: 20 before 50
        assert report.ranked_issues[0].number == 20
        assert report.ranked_issues[1].number == 50
