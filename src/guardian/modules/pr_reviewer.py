"""Pull request diff parsing and educational reviewer module."""

from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


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

            # Extract paths from header: diff --git a/path b/path
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
