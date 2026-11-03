"""Repository onboarding and codebase understanding module."""

from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field
from src.guardian.adapters.github_client import GitHubClient, GitHubNotFoundError, RepositoryMetadata


class OnboardingReport(BaseModel):
    """Structured repository onboarding summary."""

    model_config = ConfigDict(extra="ignore")

    repo_name: str = Field(description="Repository name")
    owner: str = Field(description="Repository owner")
    full_name: str = Field(description="Full name (owner/repo)")
    description: str | None = Field(default=None, description="Repository description from GitHub")
    default_branch: str = Field(default="main", description="Default branch name")
    primary_language: str | None = Field(default=None, description="Primary language reported by GitHub")
    has_readme: bool = Field(default=False, description="Whether a README was found")
    readme_summary: str | None = Field(default=None, description="Extracted introductory summary from README")
    has_contributing: bool = Field(default=False, description="Whether a CONTRIBUTING guide was found")
    setup_instructions: str | None = Field(default=None, description="Extracted setup or installation steps")
    contribution_guidelines: str | None = Field(default=None, description="Extracted contribution guidelines")
    high_level_goals: list[str] = Field(default_factory=list, description="Extracted or inferred project goals")
    detected_technologies: list[str] = Field(default_factory=list, description="Technologies identified in repo docs")
    is_inferred: dict[str, bool] = Field(
        default_factory=dict,
        description="Flags distinguishing heuristic inferences from explicit repository facts",
    )


class RepoOnboarder:
    """Extracts and organizes codebase onboarding context using the GitHub client."""

    README_CANDIDATES = ("README.md", "readme.md", "README")
    CONTRIBUTING_CANDIDATES = ("CONTRIBUTING.md", "contributing.md", ".github/CONTRIBUTING.md")

    COMMON_TECH_PATTERNS = [
        r"\bPython\b",
        r"\bFastAPI\b",
        r"\bDocker\b",
        r"\bNode(?:\.js)?\b",
        r"\bTypeScript\b",
        r"\bJavaScript\b",
        r"\bReact\b",
        r"\bVue\b",
        r"\bPostgreSQL\b",
        r"\bSQLite\b",
        r"\bRedis\b",
        r"\bSwitch\b",
        r"\bDiscord\b",
    ]

    def __init__(self, github_client: GitHubClient) -> None:
        """Initialize with an existing GitHubClient adapter."""
        self._github = github_client

    async def onboard(self, owner: str, repo: str) -> OnboardingReport:
        """Fetch repository context and compile a structured onboarding report.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            OnboardingReport containing extracted facts and heuristic summaries.
        """
        metadata = await self._github.get_repository(owner, repo)

        readme_text = await self._fetch_first_available(owner, repo, self.README_CANDIDATES)
        contributing_text = await self._fetch_first_available(owner, repo, self.CONTRIBUTING_CANDIDATES)

        has_readme = readme_text is not None
        has_contributing = contributing_text is not None

        readme_sections = self._parse_markdown_sections(readme_text or "")
        contributing_sections = self._parse_markdown_sections(contributing_text or "")

        # 1. Summary / Overview extraction
        readme_summary = self._extract_summary(readme_text, readme_sections, metadata.description)

        # 2. Setup / Installation extraction
        setup_instructions = self._extract_section_content(
            readme_sections,
            keywords=("setup", "install", "getting started", "quick start", "prerequisites", "run"),
        )
        if not setup_instructions and contributing_text:
            setup_instructions = self._extract_section_content(
                contributing_sections,
                keywords=("setup", "install", "environment", "prerequisites"),
            )

        # 3. Contribution guidelines
        contribution_guidelines: str | None = None
        if has_contributing and contributing_text:
            # If explicit CONTRIBUTING.md exists, take its opening or main instructions
            contribution_guidelines = contributing_text.strip()[:1500]
        else:
            contribution_guidelines = self._extract_section_content(
                readme_sections,
                keywords=("contribut", "development", "guidelines", "workflow"),
            )

        # 4. High-level goals
        high_level_goals, goals_inferred = self._extract_goals(
            readme_sections,
            metadata.description,
        )

        # 5. Technology detection
        detected_tech = self._detect_technologies(
            primary_language=metadata.language,
            texts=[readme_text or "", contributing_text or ""],
        )

        is_inferred = {
            "readme_summary": readme_summary != metadata.description,
            "setup_instructions": setup_instructions is not None,
            "contribution_guidelines": not has_contributing and contribution_guidelines is not None,
            "high_level_goals": goals_inferred,
            "detected_technologies": True,
        }

        return OnboardingReport(
            repo_name=metadata.name,
            owner=owner,
            full_name=metadata.full_name,
            description=metadata.description,
            default_branch=metadata.default_branch,
            primary_language=metadata.language,
            has_readme=has_readme,
            readme_summary=readme_summary,
            has_contributing=has_contributing,
            setup_instructions=setup_instructions,
            contribution_guidelines=contribution_guidelines,
            high_level_goals=high_level_goals,
            detected_technologies=detected_tech,
            is_inferred=is_inferred,
        )

    async def _fetch_first_available(
        self,
        owner: str,
        repo: str,
        candidates: tuple[str, ...],
    ) -> str | None:
        """Attempt to fetch file content from a sequence of candidate paths."""
        for path in candidates:
            try:
                return await self._github.get_file_contents(owner, repo, path)
            except GitHubNotFoundError:
                continue
        return None

    def _parse_markdown_sections(self, content: str) -> dict[str, str]:
        """Split markdown content into header -> section_body mapping."""
        if not content:
            return {}

        sections: dict[str, str] = {}
        lines = content.splitlines()
        current_header = "__intro__"
        current_lines: list[str] = []

        for line in lines:
            header_match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
            if header_match:
                if current_lines:
                    sections[current_header] = "\n".join(current_lines).strip()
                current_header = header_match.group(2).strip().lower()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_header] = "\n".join(current_lines).strip()

        return sections

    def _extract_summary(
        self,
        readme_text: str | None,
        sections: dict[str, str],
        repo_description: str | None,
    ) -> str | None:
        """Extract a readable project overview or intro paragraph."""
        if not readme_text:
            return repo_description

        # Look for intro or overview sections
        for header, body in sections.items():
            if any(k in header for k in ("overview", "about", "introduction", "__intro__")):
                clean_body = body.strip()
                if clean_body:
                    # Take first paragraph
                    first_para = clean_body.split("\n\n")[0].strip()
                    # Strip markdown links and images if leading
                    if first_para:
                        return first_para[:500]

        return repo_description

    def _extract_section_content(
        self,
        sections: dict[str, str],
        keywords: tuple[str, ...],
    ) -> str | None:
        """Find the first section whose heading matches one of the keywords."""
        for header, body in sections.items():
            if any(k in header for k in keywords):
                clean_body = body.strip()
                if clean_body:
                    return clean_body[:1000]
        return None

    def _extract_goals(
        self,
        sections: dict[str, str],
        repo_description: str | None,
    ) -> tuple[list[str], bool]:
        """Extract bulleted project goals or feature list."""
        for header, body in sections.items():
            if any(k in header for k in ("goal", "feature", "purpose", "why", "value")):
                # Extract bullet lines
                bullets = [
                    re.sub(r"^[-*+]\s+", "", line).strip()
                    for line in body.splitlines()
                    if re.match(r"^\s*[-*+]\s+", line)
                ]
                if bullets:
                    return bullets[:6], False

        # Fallback to repo description if available
        if repo_description:
            return [repo_description], True

        return [], False

    def _detect_technologies(
        self,
        primary_language: str | None,
        texts: list[str],
    ) -> list[str]:
        """Detect referenced technologies from documentation text and repo metadata."""
        found: set[str] = set()
        if primary_language:
            found.add(primary_language)

        combined = " ".join(texts)
        for pattern in self.COMMON_TECH_PATTERNS:
            matches = re.findall(pattern, combined, flags=re.IGNORECASE)
            if matches:
                # Normalize canonical name
                canonical = matches[0].capitalize()
                if canonical.lower() == "nodejs" or canonical.lower() == "node.js":
                    canonical = "Node.js"
                elif canonical.lower() == "typescript":
                    canonical = "TypeScript"
                elif canonical.lower() == "javascript":
                    canonical = "JavaScript"
                elif canonical.lower() == "fastapi":
                    canonical = "FastAPI"
                elif canonical.lower() == "postgresql":
                    canonical = "PostgreSQL"
                elif canonical.lower() == "sqlite":
                    canonical = "SQLite"
                found.add(canonical)

        return sorted(found)
