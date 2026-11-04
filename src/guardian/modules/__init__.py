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
from src.guardian.modules.pr_reviewer import (
    DiffHunk,
    DiffLine,
    FileDiff,
    parse_unified_diff,
)

__all__ = [
    "DiffHunk",
    "DiffLine",
    "FileDiff",
    "IssueDiscoveryReport",
    "IssueFinder",
    "OnboardingReport",
    "RankedIssue",
    "RepoOnboarder",
    "parse_unified_diff",
]
