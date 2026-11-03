"""Domain modules for OpenSource Guardian."""

from src.guardian.modules.issue_finder import (
    IssueDiscoveryReport,
    IssueFinder,
    RankedIssue,
)
from src.guardian.modules.onboarding import (
    OnboardingReport,
    RepoOnboarder,
)

__all__ = [
    "IssueDiscoveryReport",
    "IssueFinder",
    "OnboardingReport",
    "RankedIssue",
    "RepoOnboarder",
]
