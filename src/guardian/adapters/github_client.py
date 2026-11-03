"""Asynchronous GitHub REST API client."""

from __future__ import annotations

import base64
from typing import Any
import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from src.guardian.config.settings import Settings, get_settings


# ---------------------------------------------------------------------------
# Typed Domain Models
# ---------------------------------------------------------------------------

class RepositoryMetadata(BaseModel):
    """Normalized repository metadata."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Repository name")
    full_name: str = Field(description="Full name including owner (owner/repo)")
    description: str | None = Field(default=None, description="Repository description")
    default_branch: str = Field(default="main", description="Default branch name")
    is_fork: bool = Field(default=False, description="Whether this is a fork")
    stargazers_count: int = Field(default=0, description="Star count")
    open_issues_count: int = Field(default=0, description="Open issues count")
    html_url: str = Field(description="Web URL for the repository")
    language: str | None = Field(default=None, description="Primary programming language")


class IssueSummary(BaseModel):
    """Normalized issue summary, excluding pull requests."""

    model_config = ConfigDict(extra="ignore")

    number: int = Field(description="Issue number")
    title: str = Field(description="Issue title")
    body: str | None = Field(default=None, description="Issue body/description")
    state: str = Field(default="open", description="Issue state (e.g. open)")
    html_url: str = Field(description="Web URL for the issue")
    labels: list[str] = Field(default_factory=list, description="List of label names")
    author: str | None = Field(default=None, description="Issue author login")
    comments_count: int = Field(default=0, description="Number of comments")
    created_at: str = Field(description="Creation ISO timestamp")


# ---------------------------------------------------------------------------
# Exception Hierarchy
# ---------------------------------------------------------------------------

class GitHubError(Exception):
    """Base exception for all GitHub API interactions."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GitHubAuthError(GitHubError):
    """Raised on authentication (401) or permission/forbidden (403) errors."""


class GitHubNotFoundError(GitHubError):
    """Raised when a repository, file, issue, or pull request is not found (404)."""


class GitHubRateLimitError(GitHubError):
    """Raised when the GitHub API rate limit is exceeded (429 or rate-limited 403)."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        reset_time: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.reset_time = reset_time


class GitHubNetworkError(GitHubError):
    """Raised on network failures, connection drops, or request timeouts."""


# ---------------------------------------------------------------------------
# GitHub Client
# ---------------------------------------------------------------------------

class GitHubClient:
    """Async client for interacting with the GitHub REST API v3."""

    DEFAULT_TIMEOUT = 10.0
    API_VERSION = "2022-11-28"

    def __init__(
        self,
        token: str | SecretStr | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the GitHub client.

        Args:
            token: Optional GitHub token. If omitted, reads from application settings.
            base_url: Optional API base URL. Defaults to settings or https://api.github.com.
            client: Optional pre-configured httpx.AsyncClient (e.g. for mock testing).
            settings: Optional Settings instance. Defaults to get_settings().
        """
        app_settings = settings or get_settings()

        resolved_token = token if token is not None else app_settings.github_token
        if isinstance(resolved_token, SecretStr):
            self._token: str | None = resolved_token.get_secret_value()
        else:
            self._token = resolved_token

        self._base_url = (base_url or app_settings.github_api_base_url).rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT)

    @property
    def base_url(self) -> str:
        """Return the configured base URL."""
        return self._base_url

    def _get_headers(self, custom_accept: str | None = None) -> dict[str, str]:
        """Construct standard GitHub REST API headers."""
        headers = {
            "Accept": custom_accept or "application/vnd.github+json",
            "X-GitHub-Api-Version": self.API_VERSION,
            "User-Agent": "OpenSource-Guardian",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Translate non-2xx HTTP responses into typed domain exceptions."""
        status = response.status_code

        # Rate Limit detection (primary or secondary rate limits)
        remaining = response.headers.get("x-ratelimit-remaining")
        is_rate_limit = (
            status == 429
            or (status == 403 and remaining == "0")
            or (status == 403 and "rate limit" in response.text.lower())
        )
        if is_rate_limit:
            reset_header = response.headers.get("x-ratelimit-reset")
            reset_time = int(reset_header) if reset_header and reset_header.isdigit() else None
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded. Please wait before retrying.",
                status_code=status,
                reset_time=reset_time,
            )

        if status in (401, 403):
            raise GitHubAuthError(
                f"GitHub access denied (HTTP {status}): check authentication and permissions.",
                status_code=status,
            )

        if status == 404:
            raise GitHubNotFoundError(
                f"Resource not found on GitHub: {response.request.url.path}",
                status_code=404,
            )

        raise GitHubError(
            f"GitHub API request failed with status HTTP {status}.",
            status_code=status,
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        custom_accept: str | None = None,
    ) -> httpx.Response:
        """Execute an asynchronous HTTP request with error handling."""
        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = self._get_headers(custom_accept=custom_accept)

        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise GitHubNetworkError(f"Request to GitHub timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise GitHubNetworkError(f"Network error while contacting GitHub: {url}") from exc

        if response.is_error:
            self._handle_error_response(response)

        return response

    # -----------------------------------------------------------------------
    # Public Client Capabilities
    # -----------------------------------------------------------------------

    async def get_repository(self, owner: str, repo: str) -> RepositoryMetadata:
        """Fetch repository metadata.

        Args:
            owner: Repository owner/organization.
            repo: Repository name.

        Returns:
            Normalized RepositoryMetadata object.
        """
        self._validate_repo_coords(owner, repo)
        response = await self._request("GET", f"/repos/{owner}/{repo}")
        data = response.json()

        return RepositoryMetadata(
            name=data.get("name", repo),
            full_name=data.get("full_name", f"{owner}/{repo}"),
            description=data.get("description"),
            default_branch=data.get("default_branch", "main"),
            is_fork=data.get("fork", False),
            stargazers_count=data.get("stargazers_count", 0),
            open_issues_count=data.get("open_issues_count", 0),
            html_url=data.get("html_url", f"https://github.com/{owner}/{repo}"),
            language=data.get("language"),
        )

    async def get_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> str:
        """Fetch repository file contents as decoded text.

        Args:
            owner: Repository owner.
            repo: Repository name.
            path: Relative path to file (e.g. 'README.md', 'CONTRIBUTING.md').
            ref: Optional branch, commit, or tag.

        Returns:
            Decoded UTF-8 string content.
        """
        self._validate_repo_coords(owner, repo)
        if not path or not path.strip():
            raise ValueError("File path cannot be empty.")

        params: dict[str, Any] = {}
        if ref:
            params["ref"] = ref

        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            params=params,
        )
        data = response.json()

        encoding = data.get("encoding")
        raw_content = data.get("content", "")

        if encoding == "base64" and raw_content:
            try:
                decoded_bytes = base64.b64decode(raw_content)
                return decoded_bytes.decode("utf-8")
            except Exception as exc:
                raise GitHubError(f"Failed to decode base64 file content for {path}") from exc

        return str(raw_content)

    async def list_open_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        limit: int = 30,
    ) -> list[IssueSummary]:
        """List open repository issues, strictly excluding pull requests.

        Args:
            owner: Repository owner.
            repo: Repository name.
            labels: Optional filter for issue labels.
            limit: Maximum issues to return (default 30, max 100).

        Returns:
            List of normalized IssueSummary objects.
        """
        self._validate_repo_coords(owner, repo)
        params: dict[str, Any] = {
            "state": "open",
            "per_page": min(max(1, limit), 100),
        }
        if labels:
            params["labels"] = ",".join(labels)

        response = await self._request("GET", f"/repos/{owner}/{repo}/issues", params=params)
        raw_items = response.json()

        issues: list[IssueSummary] = []
        for item in raw_items:
            # GitHub's /issues endpoint returns both issues and pull requests;
            # pull requests include a 'pull_request' key which we strictly exclude.
            if "pull_request" in item:
                continue

            label_names = [lbl.get("name", "") for lbl in item.get("labels", []) if isinstance(lbl, dict)]

            user_obj = item.get("user") or {}
            author_login = user_obj.get("login") if isinstance(user_obj, dict) else None

            issues.append(
                IssueSummary(
                    number=item.get("number", 0),
                    title=item.get("title", ""),
                    body=item.get("body"),
                    state=item.get("state", "open"),
                    html_url=item.get("html_url", ""),
                    labels=label_names,
                    author=author_login,
                    comments_count=item.get("comments", 0),
                    created_at=item.get("created_at", ""),
                )
            )

        return issues

    async def get_pull_request_diff(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> str:
        """Fetch the unified git diff for a pull request as text.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pull_number: Pull request number.

        Returns:
            Diff formatted as plain text.
        """
        self._validate_repo_coords(owner, repo)
        if pull_number <= 0:
            raise ValueError("Pull request number must be positive.")

        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            custom_accept="application/vnd.github.v3.diff",
        )
        return response.text

    # -----------------------------------------------------------------------
    # Lifecycle & Validation
    # -----------------------------------------------------------------------

    def _validate_repo_coords(self, owner: str, repo: str) -> None:
        """Validate owner and repo coordinates."""
        if not owner or not owner.strip():
            raise ValueError("Repository owner cannot be empty.")
        if not repo or not repo.strip():
            raise ValueError("Repository name cannot be empty.")

    async def aclose(self) -> None:
        """Close the underlying HTTP client if owned by this instance."""
        if self._owns_client and self._client:
            await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        """Async context manager enter."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.aclose()
