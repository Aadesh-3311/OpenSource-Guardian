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
    PRReviewReport,
    PRReviewer,
    ReviewFinding,
    parse_unified_diff,
)

__all__ = [
    "DiffHunk",
    "DiffLine",
    "FileDiff",
    "IssueDiscoveryReport",
    "IssueFinder",
    "OnboardingReport",
    "PRReviewReport",
    "PRReviewer",
    "RankedIssue",
    "RepoOnboarder",
    "ReviewFinding",
    "parse_unified_diff",
]
