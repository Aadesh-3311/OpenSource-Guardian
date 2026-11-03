"""Unit tests for the asynchronous GitHub REST API client using mock transports."""

import base64
import httpx
import pytest
from pydantic import SecretStr

from src.guardian.adapters.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    PullRequestMetadata,
)
from src.guardian.config.settings import Settings


@pytest.mark.anyio
async def test_get_repository_metadata_success() -> None:
    """Verify repository metadata retrieval and normalization."""
    mock_data = {
        "name": "OpenSource-Guardian",
        "full_name": "aadesh-2006/OpenSource-Guardian",
        "description": "Switch-powered AI teammate",
        "default_branch": "main",
        "fork": False,
        "stargazers_count": 42,
        "open_issues_count": 5,
        "html_url": "https://github.com/aadesh-2006/OpenSource-Guardian",
        "language": "Python",
    }

    recorded_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json=mock_data)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(
            token="ghp_test_token",
            base_url="https://api.github.com",
            client=http_client,
        )
        repo = await client.get_repository("aadesh-2006", "OpenSource-Guardian")

        assert repo.name == "OpenSource-Guardian"
        assert repo.full_name == "aadesh-2006/OpenSource-Guardian"
        assert repo.stargazers_count == 42
        assert repo.default_branch == "main"
        assert repo.is_fork is False
        assert repo.language == "Python"

    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.method == "GET"
    assert req.url.path == "/repos/aadesh-2006/OpenSource-Guardian"
    assert req.headers["Authorization"] == "Bearer ghp_test_token"
    assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert req.headers["User-Agent"] == "OpenSource-Guardian"


@pytest.mark.anyio
async def test_get_file_contents_base64_decoding() -> None:
    """Verify base64-encoded file contents are correctly decoded."""
    raw_markdown = "# OpenSource Guardian\nWelcome!"
    encoded_b64 = base64.b64encode(raw_markdown.encode("utf-8")).decode("utf-8")

    mock_response = {
        "name": "README.md",
        "path": "README.md",
        "encoding": "base64",
        "content": encoded_b64,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/aadesh-2006/OpenSource-Guardian/contents/README.md"
        assert request.url.params.get("ref") == "develop"
        return httpx.Response(200, json=mock_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        content = await client.get_file_contents(
            "aadesh-2006",
            "OpenSource-Guardian",
            "README.md",
            ref="develop",
        )
        assert content == raw_markdown


@pytest.mark.anyio
async def test_list_open_issues_filters_out_pull_requests() -> None:
    """Ensure list_open_issues excludes items that are actually pull requests."""
    mock_items = [
        {
            "number": 101,
            "title": "Add documentation for Switch agent",
            "body": "Need clear docs",
            "state": "open",
            "html_url": "https://github.com/aadesh-2006/OpenSource-Guardian/issues/101",
            "labels": [{"name": "documentation"}, {"name": "good first issue"}],
            "user": {"login": "contributor1"},
            "comments": 2,
            "created_at": "2026-11-04T00:00:00Z",
        },
        {
            "number": 102,
            "title": "Fix bug in parser",
            "body": "PR description",
            "state": "open",
            "html_url": "https://github.com/aadesh-2006/OpenSource-Guardian/pull/102",
            "pull_request": {"url": "https://api.github.com/repos/aadesh-2006/OpenSource-Guardian/pulls/102"},
            "labels": [{"name": "bug"}],
            "user": {"login": "developer2"},
            "comments": 0,
            "created_at": "2026-11-04T01:00:00Z",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/aadesh-2006/OpenSource-Guardian/issues"
        assert request.url.params["state"] == "open"
        assert request.url.params["labels"] == "good first issue,help wanted"
        return httpx.Response(200, json=mock_items)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        issues = await client.list_open_issues(
            "aadesh-2006",
            "OpenSource-Guardian",
            labels=["good first issue", "help wanted"],
        )

        assert len(issues) == 1
        issue = issues[0]
        assert issue.number == 101
        assert issue.title == "Add documentation for Switch agent"
        assert issue.labels == ["documentation", "good first issue"]
        assert issue.author == "contributor1"


@pytest.mark.anyio
async def test_get_pull_request_diff_success() -> None:
    """Verify pull request diff retrieval sets appropriate Accept header and returns text."""
    sample_diff = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/aadesh-2006/OpenSource-Guardian/pulls/42"
        assert request.headers["Accept"] == "application/vnd.github.v3.diff"
        return httpx.Response(200, text=sample_diff)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        diff = await client.get_pull_request_diff("aadesh-2006", "OpenSource-Guardian", 42)
        assert diff == sample_diff


@pytest.mark.anyio
async def test_auth_error_handling_401() -> None:
    """Verify 401 response raises GitHubAuthError without exposing token."""
    secret_token = "ghp_secret_should_not_leak"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token=SecretStr(secret_token), client=http_client)

        with pytest.raises(GitHubAuthError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")

        assert exc_info.value.status_code == 401
        assert secret_token not in str(exc_info.value)


@pytest.mark.anyio
async def test_not_found_error_handling_404() -> None:
    """Verify 404 response raises GitHubNotFoundError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)

        with pytest.raises(GitHubNotFoundError) as exc_info:
            await client.get_repository("aadesh-2006", "nonexistent-repo")

        assert exc_info.value.status_code == 404
        assert "Resource not found" in str(exc_info.value)


@pytest.mark.anyio
async def test_rate_limit_error_handling_403_and_429() -> None:
    """Verify rate limit detection via 429 and 403 with x-ratelimit-remaining."""
    # Test 403 with rate limit exhausted header
    def handler_403(request: httpx.Request) -> httpx.Response:
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1730700000"}
        return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=headers)

    transport_403 = httpx.MockTransport(handler_403)
    async with httpx.AsyncClient(transport=transport_403) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubRateLimitError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")
        assert exc_info.value.status_code == 403
        assert exc_info.value.reset_time == 1730700000

    # Test 429
    def handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too Many Requests"})

    transport_429 = httpx.MockTransport(handler_429)
    async with httpx.AsyncClient(transport=transport_429) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubRateLimitError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")
        assert exc_info.value.status_code == 429


@pytest.mark.anyio
async def test_network_and_timeout_error_handling() -> None:
    """Verify connection failure and timeouts raise GitHubNetworkError."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubNetworkError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")
        assert "timed out" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_input_validation() -> None:
    """Ensure invalid repository coordinates and paths raise ValueError."""
    client = GitHubClient()
    with pytest.raises(ValueError, match="owner cannot be empty"):
        await client.get_repository("", "repo")

    with pytest.raises(ValueError, match="name cannot be empty"):
        await client.get_repository("owner", " ")

    with pytest.raises(ValueError, match="path cannot be empty"):
        await client.get_file_contents("owner", "repo", " ")

    with pytest.raises(ValueError, match="number must be positive"):
        await client.get_pull_request_diff("owner", "repo", -1)

    await client.aclose()


@pytest.mark.anyio
async def test_client_lifecycle_context_manager() -> None:
    """Verify async context manager correctly initializes and closes client."""
    async with GitHubClient(base_url="https://api.github.com") as client:
        assert client.base_url == "https://api.github.com"
        assert not client._client.is_closed

    assert client._client.is_closed


@pytest.mark.anyio
async def test_permission_error_vs_secondary_rate_limit_403() -> None:
    """Verify standard 403 raises GitHubAuthError while secondary rate-limit 403 raises GitHubRateLimitError."""
    # 1. Standard 403 Forbidden without rate-limit indicators
    def handler_permission(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible by integration"})

    transport_perm = httpx.MockTransport(handler_permission)
    async with httpx.AsyncClient(transport=transport_perm) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubAuthError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")
        assert exc_info.value.status_code == 403
        assert "access denied" in str(exc_info.value).lower()

    # 2. 403 with secondary rate limit body
    def handler_sec_rate_limit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "You have exceeded a secondary rate limit. Please wait a few minutes."})

    transport_sec = httpx.MockTransport(handler_sec_rate_limit)
    async with httpx.AsyncClient(transport=transport_sec) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubRateLimitError) as exc_info:
            await client.get_repository("aadesh-2006", "OpenSource-Guardian")
        assert exc_info.value.status_code == 403
        assert "rate limit exceeded" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_injected_client_lifecycle_preserved() -> None:
    """Verify GitHubClient does NOT close an injected AsyncClient upon exit or aclose()."""
    async with httpx.AsyncClient() as shared_client:
        async with GitHubClient(client=shared_client) as client:
            assert not client._client.is_closed

        # Shared client must remain open after GitHubClient exit
        assert not shared_client.is_closed

    assert shared_client.is_closed


@pytest.mark.anyio
async def test_get_pull_request_metadata_success() -> None:
    """Verify successful pull request metadata retrieval and field mapping."""
    mock_pr = {
        "number": 42,
        "title": "Add educational reviewer module",
        "state": "open",
        "html_url": "https://github.com/aadesh-2006/OpenSource-Guardian/pull/42",
        "user": {"login": "octocat"},
        "base": {"ref": "main"},
        "head": {"ref": "feature-pr-reviewer"},
        "additions": 150,
        "deletions": 10,
        "changed_files": 4,
        "body": "Implements the PR review heuristics.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/aadesh-2006/OpenSource-Guardian/pulls/42"
        return httpx.Response(200, json=mock_pr)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        pr = await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", 42)

        assert isinstance(pr, PullRequestMetadata)
        assert pr.number == 42
        assert pr.title == "Add educational reviewer module"
        assert pr.state == "open"
        assert pr.author == "octocat"
        assert pr.base_branch == "main"
        assert pr.head_branch == "feature-pr-reviewer"
        assert pr.additions == 150
        assert pr.deletions == 10
        assert pr.changed_files == 4
        assert pr.body == "Implements the PR review heuristics."


@pytest.mark.anyio
async def test_get_pull_request_metadata_nullable_fields() -> None:
    """Verify pull request metadata handles missing/null body and missing user object."""
    mock_pr = {
        "number": 7,
        "title": "Quick fix",
        "state": "closed",
        "html_url": "https://github.com/aadesh-2006/OpenSource-Guardian/pull/7",
        "user": None,
        "base": None,
        "head": None,
        "body": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_pr)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        pr = await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", 7)

        assert pr.number == 7
        assert pr.author is None
        assert pr.body is None
        assert pr.base_branch is None
        assert pr.head_branch is None
        assert pr.additions == 0
        assert pr.deletions == 0


@pytest.mark.anyio
async def test_get_pull_request_metadata_not_found() -> None:
    """Verify 404 response raises GitHubNotFoundError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(client=http_client)
        with pytest.raises(GitHubNotFoundError) as exc_info:
            await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", 999)

        assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_get_pull_request_metadata_auth_error() -> None:
    """Verify 401 response raises GitHubAuthError without leaking credentials."""
    secret = "ghp_super_secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubClient(token=SecretStr(secret), client=http_client)
        with pytest.raises(GitHubAuthError) as exc_info:
            await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", 42)

        assert exc_info.value.status_code == 401
        assert secret not in str(exc_info.value)


@pytest.mark.anyio
async def test_get_pull_request_metadata_invalid_number() -> None:
    """Verify invalid PR numbers (<= 0) raise ValueError."""
    client = GitHubClient()
    with pytest.raises(ValueError, match="positive"):
        await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", 0)

    with pytest.raises(ValueError, match="positive"):
        await client.get_pull_request("aadesh-2006", "OpenSource-Guardian", -5)

    await client.aclose()
