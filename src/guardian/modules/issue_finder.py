"""Beginner-friendly issue discovery and deterministic ranking module."""

from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field
from src.guardian.adapters.github_client import GitHubClient, IssueSummary


class RankedIssue(BaseModel):
    """Normalized issue with an explicit, deterministic suitability score."""

    model_config = ConfigDict(extra="ignore")

    number: int = Field(description="Issue number")
    title: str = Field(description="Issue title")
    html_url: str = Field(description="Web URL for the issue")
    author: str | None = Field(default=None, description="Issue creator login")
    labels: list[str] = Field(default_factory=list, description="Labels associated with the issue")
    suitability_score: int = Field(
        ge=0,
        le=100,
        description="Deterministic heuristic score (0-100) reflecting beginner friendliness",
    )
    score_reasons: list[str] = Field(
        default_factory=list,
        description="Explicit breakdown of positive scoring factors",
    )
    comments_count: int = Field(default=0, description="Number of comments on the issue")
    created_at: str = Field(description="ISO creation timestamp")
    body_excerpt: str | None = Field(default=None, description="Brief preview of issue description")


class IssueDiscoveryReport(BaseModel):
    """Collection of ranked issues and evaluation metadata."""

    model_config = ConfigDict(extra="ignore")

    owner: str = Field(description="Repository owner")
    repo: str = Field(description="Repository name")
    total_found: int = Field(description="Total issues evaluated")
    ranked_issues: list[RankedIssue] = Field(description="Deterministic ranking of candidate issues")
    disclaimer: str = Field(
        default=(
            "Heuristic suitability scores are based on label signals, description clarity, "
            "and comment activity. They provide starting recommendations and do not guarantee "
            "issue difficulty or assignment status."
        ),
        description="Clarification that scores are heuristic rather than guarantees",
    )


class IssueFinder:
    """Discovers and ranks candidate issues for new open-source contributors."""

    # Explicit label weights
    LABEL_WEIGHTS: dict[str, int] = {
        "good first issue": 35,
        "good-first-issue": 35,
        "beginner": 30,
        "beginner-friendly": 30,
        "help wanted": 25,
        "help-wanted": 25,
        "documentation": 20,
        "docs": 20,
    }

    def __init__(self, github_client: GitHubClient) -> None:
        """Initialize with an existing GitHubClient adapter."""
        self._github = github_client

    async def find_issues(
        self,
        owner: str,
        repo: str,
        labels: list[str] | None = None,
        limit: int = 10,
    ) -> IssueDiscoveryReport:
        """Fetch open issues, apply heuristic scoring, and return a deterministically sorted report.

        Args:
            owner: Repository owner.
            repo: Repository name.
            labels: Optional label filter.
            limit: Maximum ranked issues to return in the report.

        Returns:
            IssueDiscoveryReport containing ranked issues and scoring transparency.
        """
        # Fetch candidate issues using the adapter
        raw_issues = await self._github.list_open_issues(
            owner=owner,
            repo=repo,
            labels=labels,
            limit=max(limit * 2, 30),
        )

        ranked: list[RankedIssue] = []
        for issue in raw_issues:
            ranked_item = self.score_issue(issue)
            ranked.append(ranked_item)

        # Deterministic sorting:
        # Primary: suitability_score descending (-score)
        # Secondary: comments_count ascending (fewer comments first)
        # Tertiary: issue number ascending (stable tie-breaker)
        ranked.sort(key=lambda item: (-item.suitability_score, item.comments_count, item.number))

        selected = ranked[:limit]

        return IssueDiscoveryReport(
            owner=owner,
            repo=repo,
            total_found=len(raw_issues),
            ranked_issues=selected,
        )

    def score_issue(self, issue: IssueSummary) -> RankedIssue:
        """Compute an explicit, deterministic suitability score for an issue.

        Scoring Components:
        1. Target Labels (up to 50 pts):
           - 'good first issue' / 'beginner': +35 / +30 pts
           - 'help wanted': +25 pts
           - 'documentation' / 'docs': +20 pts
        2. Description Quality (up to 30 pts):
           - Has description: +10 pts
           - Description length > 100 chars: +10 pts
           - Structured formatting (code block, checklist, or bullets): +10 pts
        3. Contributor Accessibility (up to 20 pts):
           - 0 comments (unclaimed / fresh): +20 pts
           - 1-2 comments (light discussion): +15 pts
           - 3-5 comments (active thread): +10 pts
           - >5 comments: 0 pts (often contested or already being worked on)
        """
        score = 0
        reasons: list[str] = []

        # 1. Label scoring
        label_score = 0
        for lbl in issue.labels:
            normalized_lbl = lbl.lower().strip()
            if normalized_lbl in self.LABEL_WEIGHTS:
                weight = self.LABEL_WEIGHTS[normalized_lbl]
                label_score += weight
                reasons.append(f"Label '{lbl}' (+{weight} pts)")

        label_score = min(label_score, 50)
        score += label_score

        # 2. Description quality
        body = (issue.body or "").strip()
        if body:
            score += 10
            reasons.append("Has issue description (+10 pts)")

            if len(body) >= 100:
                score += 10
                reasons.append("Detailed description (> 100 characters) (+10 pts)")

            # Check for structured markdown: code blocks (``` or `), checklists (- [ ]), bullets
            has_code = "```" in body or "`" in body
            has_checklist = bool(re.search(r"-\s*\[[ xX]\]", body))
            has_bullets = bool(re.search(r"(?m)^\s*[-*+]\s+", body))

            if has_code or has_checklist or has_bullets:
                score += 10
                reasons.append("Contains structured guidance or code snippet (+10 pts)")

        # 3. Contributor accessibility / comments
        if issue.comments_count == 0:
            score += 20
            reasons.append("Zero comments / likely unclaimed (+20 pts)")
        elif 1 <= issue.comments_count <= 2:
            score += 15
            reasons.append("Light discussion (1-2 comments) (+15 pts)")
        elif 3 <= issue.comments_count <= 5:
            score += 10
            reasons.append("Moderate discussion (3-5 comments) (+10 pts)")
        else:
            reasons.append("Heavy discussion (>5 comments) (0 accessibility pts)")

        final_score = min(score, 100)

        # Excerpt preparation (first 200 chars)
        excerpt = body[:200] + ("..." if len(body) > 200 else "") if body else None

        return RankedIssue(
            number=issue.number,
            title=issue.title,
            html_url=issue.html_url,
            author=issue.author,
            labels=issue.labels,
            suitability_score=final_score,
            score_reasons=reasons,
            comments_count=issue.comments_count,
            created_at=issue.created_at,
            body_excerpt=excerpt,
        )
