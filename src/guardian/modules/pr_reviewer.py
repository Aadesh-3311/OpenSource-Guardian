"""Pull request diff parsing and educational reviewer module."""

from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from src.guardian.adapters.github_client import GitHubClient, PullRequestMetadata


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class DiffLine(BaseModel):
    """Represents a single line within a diff hunk."""

    model_config = ConfigDict(extra="ignore")

    origin: Literal["+", "-", " "] = Field(description="Line origin: '+' added, '-' deleted, ' ' context")
    content: str = Field(description="Content of the line without the origin prefix")
    old_line_number: int | None = Field(default=None, description="Line number in the old file, if applicable")
    new_line_number: int | None = Field(default=None, description="Line number in the new file, if applicable")


class DiffHunk(BaseModel):
    """Represents a unified diff hunk."""

    model_config = ConfigDict(extra="ignore")

    old_start: int = Field(description="Old file start line")
    old_lines: int = Field(description="Old file line count")
    new_start: int = Field(description="New file start line")
    new_lines: int = Field(description="New file line count")
    header: str = Field(description="Full hunk header line including optional section text")
    lines: list[DiffLine] = Field(default_factory=list, description="Lines contained in this hunk")


class FileDiff(BaseModel):
    """Represents the complete diff for a single file."""

    model_config = ConfigDict(extra="ignore")

    file_path: str = Field(description="Target or active file path")
    old_path: str | None = Field(default=None, description="Previous file path in renames")
    status: Literal["added", "modified", "deleted", "renamed"] = Field(
        default="modified",
        description="Type of modification",
    )
    is_binary: bool = Field(default=False, description="Whether the file is binary")
    additions: int = Field(default=0, description="Count of added lines")
    deletions: int = Field(default=0, description="Count of deleted lines")
    hunks: list[DiffHunk] = Field(default_factory=list, description="Hunks belonging to this file")


class ReviewFinding(BaseModel):
    """An educational review finding with location and actionable suggestion."""

    model_config = ConfigDict(extra="ignore")

    category: Literal["SECURITY", "TESTING", "DOCUMENTATION", "CODE_QUALITY", "PR_HYGIENE"] = Field(
        description="Category of the finding"
    )
    severity: Literal["INFO", "WARNING", "CRITICAL"] = Field(
        description="Severity level: INFO, WARNING, or CRITICAL"
    )
    message: str = Field(description="Educational explanation of the observation")
    file_path: str | None = Field(default=None, description="Affected file path")
    line_number: int | None = Field(default=None, description="Line number in the new file")
    suggestion: str = Field(description="Constructive, actionable suggestion")


class PRReviewReport(BaseModel):
    """Structured educational review report for a pull request."""

    model_config = ConfigDict(extra="ignore")

    pr_number: int = Field(description="Pull request number")
    repo: str = Field(description="Repository context")
    title: str | None = Field(default=None, description="Pull request title")
    author: str | None = Field(default=None, description="Pull request author")
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        default="LOW",
        description="Assessed review risk level based on scope and findings",
    )
    files_analyzed: int = Field(default=0, description="Number of files analyzed")
    additions: int = Field(default=0, description="Total additions across all diffs")
    deletions: int = Field(default=0, description="Total deletions across all diffs")
    findings: list[ReviewFinding] = Field(default_factory=list, description="Prioritized list of review findings")
    positive_notes: list[str] = Field(default_factory=list, description="Positive observations encouraging good practices")
    formatted_markdown: str = Field(default="", description="Ready-to-post Markdown review report")
    disclaimer: str = Field(
        default=(
            "Heuristic educational review based on static unified diff analysis. "
            "Code was not compiled or executed. Review findings are suggestions to support maintainers "
            "and contributors, not definitive defect confirmations."
        ),
        description="Clarification that analysis is heuristic and non-executable",
    )


# ---------------------------------------------------------------------------
# Unified Diff Parser
# ---------------------------------------------------------------------------

HUNK_HEADER_PATTERN = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$"
)


def _clean_diff_path(raw_path: str) -> str:
    """Strip leading diff prefixes ('a/', 'b/') and enclosing quotes."""
    path = raw_path.strip()
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        path = path[1:-1]
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _extract_git_diff_paths(header_line: str) -> tuple[str, str]:
    """Extract old and new paths from a 'diff --git ...' header line."""
    line = header_line[len("diff --git "):].strip()
    # Check for quoted paths: "a/..." "b/..."
    if line.startswith('"'):
        quoted_match = re.match(r'^"a/(.+?)"\s+"b/(.+?)"$', line)
        if quoted_match:
            return quoted_match.group(1), quoted_match.group(2)
    # Check for standard ' a/' and ' b/'
    if " b/" in line:
        b_idx = line.rfind(" b/")
        a_part = line[:b_idx].strip()
        b_part = line[b_idx + len(" b/"):].strip()
        if a_part.startswith("a/"):
            a_part = a_part[2:]
        return a_part, b_part
    return "unknown", "unknown"


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified git diff text into structured FileDiff models.

    Args:
        diff_text: Raw diff string as returned by git diff or GitHub's diff API.

    Returns:
        List of FileDiff objects with line-accurate DiffHunks.
    """
    if not diff_text or not diff_text.strip():
        return []

    lines = diff_text.splitlines()
    files: list[FileDiff] = []

    current_file: FileDiff | None = None
    current_hunk: DiffHunk | None = None

    current_old_line = 0
    current_new_line = 0

    idx = 0
    total_lines = len(lines)

    while idx < total_lines:
        line = lines[idx]

        # 1. New file boundary: 'diff --git a/... b/...'
        if line.startswith("diff --git "):
            # Finalize previous hunk & file
            if current_hunk is not None and current_file is not None:
                current_file.hunks.append(current_hunk)
                current_hunk = None
            if current_file is not None:
                files.append(current_file)

            old_p, new_p = _extract_git_diff_paths(line)

            current_file = FileDiff(
                file_path=new_p,
                old_path=old_p if old_p != new_p else None,
                status="modified",
            )
            idx += 1
            continue

        # If we have no active file, create a fallback file for standalone diffs
        if current_file is None:
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
                current_file = FileDiff(file_path="unknown", status="modified")
            else:
                idx += 1
                continue

        # 2. Status & Metadata headers
        if line.startswith("new file mode "):
            current_file.status = "added"
            idx += 1
            continue
        elif line.startswith("deleted file mode "):
            current_file.status = "deleted"
            idx += 1
            continue
        elif line.startswith("rename from "):
            current_file.old_path = line[len("rename from "):].strip()
            current_file.status = "renamed"
            idx += 1
            continue
        elif line.startswith("rename to "):
            current_file.file_path = line[len("rename to "):].strip()
            current_file.status = "renamed"
            idx += 1
            continue
        elif line.startswith("--- "):
            raw_path = line[4:].strip()
            if raw_path == "/dev/null":
                current_file.status = "added"
            elif not current_file.old_path:
                current_file.old_path = _clean_diff_path(raw_path)
            idx += 1
            continue
        elif line.startswith("+++ "):
            raw_path = line[4:].strip()
            if raw_path == "/dev/null":
                current_file.status = "deleted"
                if current_file.old_path:
                    current_file.file_path = current_file.old_path
            else:
                cleaned = _clean_diff_path(raw_path)
                current_file.file_path = cleaned
            idx += 1
            continue
        elif "Binary files " in line and " differ" in line or line.startswith("GIT binary patch"):
            current_file.is_binary = True
            if "/dev/null and " in line:
                current_file.status = "added"
            elif " and /dev/null differ" in line:
                current_file.status = "deleted"
            idx += 1
            continue

        # 3. Hunk header: '@@ -old,len +new,len @@'
        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match:
            # Finalize previous hunk
            if current_hunk is not None:
                current_file.hunks.append(current_hunk)

            old_start = int(hunk_match.group(1))
            old_lines = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_start = int(hunk_match.group(3))
            new_lines = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                header=line,
                lines=[],
            )
            current_old_line = old_start
            current_new_line = new_start
            idx += 1
            continue

        # 4. Hunk body lines
        if current_hunk is not None:
            if line.startswith("+"):
                current_hunk.lines.append(
                    DiffLine(
                        origin="+",
                        content=line[1:],
                        old_line_number=None,
                        new_line_number=current_new_line,
                    )
                )
                current_new_line += 1
                current_file.additions += 1
            elif line.startswith("-"):
                current_hunk.lines.append(
                    DiffLine(
                        origin="-",
                        content=line[1:],
                        old_line_number=current_old_line,
                        new_line_number=None,
                    )
                )
                current_old_line += 1
                current_file.deletions += 1
            elif line.startswith(" ") or line == "":
                # Context line
                content = line[1:] if line.startswith(" ") else ""
                current_hunk.lines.append(
                    DiffLine(
                        origin=" ",
                        content=content,
                        old_line_number=current_old_line,
                        new_line_number=current_new_line,
                    )
                )
                current_old_line += 1
                current_new_line += 1
            elif line.startswith(r"\ No newline at end of file"):
                # Metadata line, no line number advance
                pass
            else:
                # Malformed or unexpected non-diff line inside hunk; preserve gracefully
                pass

        idx += 1

    # Finalize trailing hunk & file
    if current_hunk is not None and current_file is not None:
        current_file.hunks.append(current_hunk)
    if current_file is not None:
        files.append(current_file)

    return files


# ---------------------------------------------------------------------------
# PR Reviewer & Educational Heuristics Engine
# ---------------------------------------------------------------------------

class PRReviewer:
    """Educational PR review analyzer and constructive report generator."""

    # Explicit threshold configurations
    DIFF_SIZE_LINE_WARNING = 500
    DIFF_SIZE_FILE_WARNING = 15

    SECRET_PATTERNS = [
        (re.compile(r"\bghp_[a-zA-Z0-9]{30,}\b"), "GitHub personal access token"),
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key identifier"),
        (
            re.compile(
                r"""(?i)\b(?:api_key|secret_key|client_secret|auth_token|password|passwd|private_key)\s*[:=]\s*['"][^'"]{8,}['"]"""
            ),
            "Hardcoded credential assignment",
        ),
        (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"), "Private cryptographic key"),
    ]

    DEBUG_PATTERNS = [
        (re.compile(r"\b(?:pdb\.set_trace|breakpoint|import pdb)\b"), "Python debugger/breakpoint"),
        (re.compile(r"(?<![a-zA-Z0-9_.])print\s*\("), "Console print statement"),
        (re.compile(r"\b(?:console\.log|debugger)\b"), "JavaScript console log/debugger"),
    ]

    def __init__(self, github_client: GitHubClient) -> None:
        """Initialize with an existing GitHubClient adapter."""
        self._github = github_client

    async def review_pr(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> PRReviewReport:
        """Fetch PR metadata and diff, run educational review heuristics, and generate report.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pull_number: Pull request number.

        Returns:
            PRReviewReport containing findings, positive observations, and Markdown.
        """
        pr_meta = await self._github.get_pull_request(owner, repo, pull_number)
        raw_diff = await self._github.get_pull_request_diff(owner, repo, pull_number)
        files = parse_unified_diff(raw_diff)
        return self.evaluate(pr_meta, files)

    def evaluate(
        self,
        pr_meta: PullRequestMetadata,
        files: list[FileDiff],
    ) -> PRReviewReport:
        """Pure evaluation running heuristics against parsed file diffs.

        Args:
            pr_meta: PullRequestMetadata object.
            files: List of FileDiff models.

        Returns:
            Structured PRReviewReport.
        """
        findings: list[ReviewFinding] = []
        positive_notes: list[str] = []

        total_additions = sum(f.additions for f in files)
        total_deletions = sum(f.deletions for f in files)

        # 1. Diff size / blast radius heuristic
        self._check_diff_size(files, total_additions, total_deletions, findings, positive_notes)

        # 2. Test accompaniment heuristic
        self._check_test_accompaniment(files, findings, positive_notes)

        # 3. Documentation sync heuristic
        self._check_doc_sync(files, total_additions, findings, positive_notes)

        # 4. Code smells & secret detection
        self._check_code_smells(files, findings)

        # Sort findings deterministically by severity (CRITICAL > WARNING > INFO), then file, then line
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        findings.sort(
            key=lambda f: (
                severity_order.get(f.severity, 99),
                f.file_path or "",
                f.line_number or 0,
            )
        )

        # Determine risk level
        if any(f.severity == "CRITICAL" for f in findings):
            risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "HIGH"
        elif any(f.severity == "WARNING" for f in findings):
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        # Generate formatted Markdown
        markdown = self._generate_markdown_report(
            pr_meta=pr_meta,
            files=files,
            findings=findings,
            positive_notes=positive_notes,
            risk_level=risk_level,
            total_additions=total_additions,
            total_deletions=total_deletions,
        )

        return PRReviewReport(
            pr_number=pr_meta.number,
            repo=f"{pr_meta.base_branch or 'main'}",
            title=pr_meta.title,
            author=pr_meta.author,
            risk_level=risk_level,
            files_analyzed=len(files),
            additions=total_additions,
            deletions=total_deletions,
            findings=findings,
            positive_notes=positive_notes,
            formatted_markdown=markdown,
        )

    # -----------------------------------------------------------------------
    # Heuristic Checks
    # -----------------------------------------------------------------------

    def _check_diff_size(
        self,
        files: list[FileDiff],
        additions: int,
        deletions: int,
        findings: list[ReviewFinding],
        positive_notes: list[str],
    ) -> None:
        """Evaluate change volume and blast radius."""
        total_lines = additions + deletions
        file_count = len(files)

        if total_lines > self.DIFF_SIZE_LINE_WARNING or file_count > self.DIFF_SIZE_FILE_WARNING:
            findings.append(
                ReviewFinding(
                    category="PR_HYGIENE",
                    severity="WARNING",
                    message=(
                        f"Large pull request detected ({total_lines} lines changed across {file_count} files). "
                        "Substantial change volume increases review complexity and the likelihood of subtle regressions."
                    ),
                    suggestion=(
                        "Consider splitting larger changes into smaller, focused pull requests "
                        "(e.g., separating preparatory refactoring from feature implementation)."
                    ),
                )
            )
        elif 0 < total_lines <= 200 and file_count <= 5:
            positive_notes.append(
                f"Focused pull request size ({total_lines} lines across {file_count} file(s)), "
                "facilitating faster maintainer review and lower regression risk."
            )

    def _check_test_accompaniment(
        self,
        files: list[FileDiff],
        findings: list[ReviewFinding],
        positive_notes: list[str],
    ) -> None:
        """Verify whether non-test source code changes include accompanying test updates."""
        source_files: list[str] = []
        test_files: list[str] = []

        for f in files:
            p = f.file_path.lower()
            if self._is_test_file(p):
                test_files.append(f.file_path)
            elif self._is_source_code_file(p):
                source_files.append(f.file_path)

        if source_files and not test_files:
            preview = ", ".join(source_files[:3]) + ("..." if len(source_files) > 3 else "")
            findings.append(
                ReviewFinding(
                    category="TESTING",
                    severity="WARNING",
                    message=(
                        f"Source code modifications detected in {len(source_files)} file(s) ({preview}) "
                        "without accompanying test modifications."
                    ),
                    suggestion=(
                        "Consider adding automated test cases verifying the new functionality or bug fix. "
                        "In collaborative repositories, tests protect your contribution against accidental future regressions."
                    ),
                )
            )
        elif source_files and test_files:
            positive_notes.append(
                f"Automated test updates included alongside source changes ({len(test_files)} test file(s) updated)."
            )

    def _check_doc_sync(
        self,
        files: list[FileDiff],
        additions: int,
        findings: list[ReviewFinding],
        positive_notes: list[str],
    ) -> None:
        """Check if significant code or config changes include documentation updates."""
        doc_files: list[str] = []
        config_files: list[str] = []

        for f in files:
            p = f.file_path.lower()
            if p.endswith(".md") or p.startswith("docs/"):
                doc_files.append(f.file_path)
            elif any(p.endswith(ext) for ext in (".toml", ".yaml", ".yml", ".env.example", "dockerfile")):
                config_files.append(f.file_path)

        if doc_files:
            positive_notes.append(
                f"Documentation updated alongside changes ({len(doc_files)} doc file(s) modified)."
            )
        elif (additions >= 100 or config_files) and not doc_files:
            findings.append(
                ReviewFinding(
                    category="DOCUMENTATION",
                    severity="INFO",
                    message=(
                        "Substantial logic or project configuration was modified without documentation updates."
                    ),
                    suggestion=(
                        "If this change modifies user-facing behavior, environment settings, or public APIs, "
                        "consider updating relevant documentation (e.g. README.md or docs/)."
                    ),
                )
            )

    def _check_code_smells(
        self,
        files: list[FileDiff],
        findings: list[ReviewFinding],
    ) -> None:
        """Scan added lines for hardcoded credentials and debug residue with strict masking."""
        for f in files:
            if f.is_binary:
                continue

            is_test = self._is_test_file(f.file_path.lower())

            for hunk in f.hunks:
                for line in hunk.lines:
                    # Only analyze added lines
                    if line.origin != "+":
                        continue

                    content = line.content

                    # 1. Secret scanning (CRITICAL)
                    for pattern, description in self.SECRET_PATTERNS:
                        if pattern.search(content):
                            # SECURITY MANDATE: Do not include matched secret or raw line in finding/message
                            findings.append(
                                ReviewFinding(
                                    category="SECURITY",
                                    severity="CRITICAL",
                                    message=f"Potential hardcoded credential detected ({description}).",
                                    file_path=f.file_path,
                                    line_number=line.new_line_number,
                                    suggestion=(
                                        "Secrets should never be committed to source control. Move sensitive credentials "
                                        "to environment variables or secret managers, and immediately revoke/rotate "
                                        "this secret if it was ever pushed to a remote repository."
                                    ),
                                )
                            )
                            # Once a line is flagged as a credential, skip other smell checks on that line
                            break
                    else:
                        # 2. Debug residue (INFO, non-test files only)
                        if not is_test:
                            for dbg_pattern, dbg_desc in self.DEBUG_PATTERNS:
                                if dbg_pattern.search(content):
                                    findings.append(
                                        ReviewFinding(
                                            category="CODE_QUALITY",
                                            severity="INFO",
                                            message=f"Possible debug residue detected ({dbg_desc}).",
                                            file_path=f.file_path,
                                            line_number=line.new_line_number,
                                            suggestion=(
                                                "Remove temporary debug statements or breakpoints before merging "
                                                "to keep production execution and logs clean."
                                            ),
                                        )
                                    )
                                    break

    # -----------------------------------------------------------------------
    # Helper Classifiers & Markdown Generator
    # -----------------------------------------------------------------------

    def _is_test_file(self, path_lower: str) -> bool:
        """Identify if a file path is a test file."""
        return any(
            marker in path_lower
            for marker in ("tests/", "/test/", "test_", "_test.", ".test.", ".spec.")
        )

    def _is_source_code_file(self, path_lower: str) -> bool:
        """Identify if a file path represents non-test source code."""
        code_exts = (
            ".py", ".ts", ".js", ".jsx", ".tsx", ".go", ".rs", ".java",
            ".cpp", ".c", ".h", ".cs", ".rb", ".php",
        )
        is_code = any(path_lower.endswith(ext) for ext in code_exts)
        is_config = any(
            path_lower.endswith(ext)
            for ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock")
        )
        return is_code and not is_config

    def _generate_markdown_report(
        self,
        pr_meta: PullRequestMetadata,
        files: list[FileDiff],
        findings: list[ReviewFinding],
        positive_notes: list[str],
        risk_level: str,
        total_additions: int,
        total_deletions: int,
    ) -> str:
        """Generate a clean, structured educational Markdown review report."""
        lines: list[str] = []

        title_display = pr_meta.title or f"PR #{pr_meta.number}"
        lines.append(f"# 🛡️ PR Guardian Review: {title_display} (#{pr_meta.number})")
        lines.append("")

        # Overview Metadata Table
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| **Author** | @{pr_meta.author or 'contributor'} |")
        lines.append(f"| **Assessed Risk Level** | **{risk_level}** |")
        lines.append(f"| **Diff Volume** | +{total_additions} / -{total_deletions} lines |")
        lines.append(f"| **Files Changed** | {len(files)} file(s) |")
        lines.append("")

        # Empty / Binary diff handling
        if not files:
            lines.append("> [!NOTE]")
            lines.append("> No textual code changes detected in this pull request (empty diff or metadata-only update).")
            lines.append("")
        elif all(f.is_binary for f in files):
            lines.append("> [!NOTE]")
            lines.append("> This pull request contains only binary assets. Source code heuristics were skipped.")
            lines.append("")

        # Positive Observations
        if positive_notes:
            lines.append("### 🌟 Positive Observations")
            for note in positive_notes:
                lines.append(f"- {note}")
            lines.append("")

        # Findings & Actionable Recommendations
        lines.append("### 🔍 Findings & Recommendations")
        if findings:
            for f in findings:
                loc = f"`{f.file_path}:{f.line_number}`" if f.file_path and f.line_number else (f"`{f.file_path}`" if f.file_path else "General")
                lines.append(f"- **[{f.severity}]** [{f.category}] {loc}: {f.message}")
                lines.append(f"  *Actionable Guidance*: {f.suggestion}")
        else:
            lines.append("- ✨ No heuristic warnings or code smells detected! The proposed changes look clean and well-scoped.")
        lines.append("")

        # Disclaimer / Educational Boundary
        lines.append("---")
        lines.append("### ℹ️ Review Disclaimer")
        lines.append(
            "This report is generated via static unified diff analysis without compiling or executing PR code. "
            "Findings are educational recommendations to assist maintainers and contributors, not automated merge blocks."
        )

        return "\n".join(lines)
