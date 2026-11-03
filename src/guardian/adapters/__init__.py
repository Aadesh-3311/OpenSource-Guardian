"""Adapters package for external services and integrations."""

from src.guardian.adapters.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNetworkError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    IssueSummary,
    PullRequestMetadata,
    RepositoryMetadata,
)

__all__ = [
    "GitHubAuthError",
    "GitHubClient",
    "GitHubError",
    "GitHubNetworkError",
    "GitHubNotFoundError",
    "GitHubRateLimitError",
    "IssueSummary",
    "PullRequestMetadata",
    "RepositoryMetadata",
]
