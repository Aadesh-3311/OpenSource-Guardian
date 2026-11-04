"""Unit tests for the unified diff parser engine."""

import pytest
import httpx
from src.guardian.adapters.github_client import GitHubClient, PullRequestMetadata
from src.guardian.modules.pr_reviewer import (
    DiffHunk,
    DiffLine,
    FileDiff,
    PRReviewReport,
    PRReviewer,
    ReviewFinding,
    parse_unified_diff,
)


SAMPLE_MULTI_FILE_DIFF = """diff --git a/src/main.py b/src/main.py
index 1234567..89abcdef 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,7 @@
 def start():
-    print("old")
+    print("new")
+    print("added line")
     return True
 
 def stop():
@@ -20,4 +22,4 @@ def helper():
-    pass
+    return 42
diff --git a/docs/README.md b/docs/README.md
new file mode 100644
index 0000000..abcdef1
--- /dev/null
+++ b/docs/README.md
@@ -0,0 +1,2 @@
+# Title
+Documentation here.
"""

SAMPLE_RENAME_DIFF = """diff --git a/old_name.py b/new_name.py
similarity index 95%
rename from old_name.py
rename to new_name.py
index 1111111..2222222 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
-import sys
+import os
 print("hello")
"""

SAMPLE_DELETED_FILE_DIFF = """diff --git a/obsolete.py b/obsolete.py
deleted file mode 100644
index 3333333..0000000
--- a/obsolete.py
+++ /dev/null
@@ -1,3 +0,0 @@
-line 1
-line 2
-line 3
"""

SAMPLE_BINARY_DIFF = """diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
index 0000000..4444444
Binary files /dev/null and b/assets/logo.png differ
"""

SAMPLE_NO_NEWLINE_DIFF = r"""diff --git a/file.txt b/file.txt
index 5555555..6666666 100644
--- a/file.txt
+++ b/file.txt
@@ -1 +1 @@
-old
\ No newline at end of file
+new
\ No newline at end of file
"""


def test_parse_empty_and_whitespace_diff() -> None:
    """Ensure empty or whitespace-only diffs return empty lists without error."""
    assert parse_unified_diff("") == []
    assert parse_unified_diff("   \n\n\t  ") == []
    assert parse_unified_diff(None) == []  # type: ignore[arg-type]


def test_parse_multi_file_and_multi_hunk_diff() -> None:
    """Verify parsing multiple files, multiple hunks, and accurate line numbering."""
    files = parse_unified_diff(SAMPLE_MULTI_FILE_DIFF)
    assert len(files) == 2

    # File 1: src/main.py
    file1 = files[0]
    assert file1.file_path == "src/main.py"
    assert file1.status == "modified"
    assert file1.is_binary is False
    assert file1.additions == 3  # +new, +added line, +return 42
    assert file1.deletions == 2  # -old, -pass
    assert len(file1.hunks) == 2

    # First hunk in src/main.py
    hunk1 = file1.hunks[0]
    assert hunk1.old_start == 1
    assert hunk1.old_lines == 5
    assert hunk1.new_start == 1
    assert hunk1.new_lines == 7

    # Inspect lines and line numbers in hunk 1
    # Line 0: context 'def start():' (old: 1, new: 1)
    assert hunk1.lines[0].origin == " "
    assert hunk1.lines[0].old_line_number == 1
    assert hunk1.lines[0].new_line_number == 1

    # Line 1: deletion '-    print("old")' (old: 2, new: None)
    assert hunk1.lines[1].origin == "-"
    assert hunk1.lines[1].old_line_number == 2
    assert hunk1.lines[1].new_line_number is None
    assert 'print("old")' in hunk1.lines[1].content

    # Line 2: addition '+    print("new")' (old: None, new: 2)
    assert hunk1.lines[2].origin == "+"
    assert hunk1.lines[2].old_line_number is None
    assert hunk1.lines[2].new_line_number == 2
    assert 'print("new")' in hunk1.lines[2].content

    # Line 3: addition '+    print("added line")' (old: None, new: 3)
    assert hunk1.lines[3].origin == "+"
    assert hunk1.lines[3].old_line_number is None
    assert hunk1.lines[3].new_line_number == 3

    # File 2: docs/README.md (new file)
    file2 = files[1]
    assert file2.file_path == "docs/README.md"
    assert file2.status == "added"
    assert file2.additions == 2
    assert file2.deletions == 0
    assert len(file2.hunks) == 1
    assert file2.hunks[0].lines[0].origin == "+"
    assert file2.hunks[0].lines[0].new_line_number == 1


def test_parse_rename_diff() -> None:
    """Verify parsing file renames with old and new paths."""
    files = parse_unified_diff(SAMPLE_RENAME_DIFF)
    assert len(files) == 1

    file = files[0]
    assert file.status == "renamed"
    assert file.old_path == "old_name.py"
    assert file.file_path == "new_name.py"
    assert file.additions == 1
    assert file.deletions == 1


def test_parse_deleted_file_diff() -> None:
    """Verify parsing deleted files."""
    files = parse_unified_diff(SAMPLE_DELETED_FILE_DIFF)
    assert len(files) == 1

    file = files[0]
    assert file.status == "deleted"
    assert file.file_path == "obsolete.py"
    assert file.deletions == 3
    assert file.additions == 0


def test_parse_binary_diff() -> None:
    """Verify binary file diff notification without content parsing."""
    files = parse_unified_diff(SAMPLE_BINARY_DIFF)
    assert len(files) == 1

    file = files[0]
    assert file.file_path == "assets/logo.png"
    assert file.status == "added"
    assert file.is_binary is True
    assert file.additions == 0
    assert file.deletions == 0
    assert len(file.hunks) == 0

    # Test binary file deleted
    binary_deleted_diff = """diff --git a/assets/old_logo.png b/assets/old_logo.png
deleted file mode 100644
Binary files a/assets/old_logo.png and /dev/null differ
"""
    del_files = parse_unified_diff(binary_deleted_diff)
    assert len(del_files) == 1
    assert del_files[0].file_path == "assets/old_logo.png"
    assert del_files[0].status == "deleted"
    assert del_files[0].is_binary is True


def test_parse_paths_with_spaces() -> None:
    """Verify parsing paths with spaces (both quoted and unquoted)."""
    diff_with_spaces = """diff --git "a/my directory/file name.py" "b/my directory/file name.py"
index 1111..2222 100644
--- "a/my directory/file name.py"
+++ "b/my directory/file name.py"
@@ -1 +1 @@
-old
+new
diff --git a/unquoted path with space/script.py b/unquoted path with space/script.py
index 3333..4444 100644
--- a/unquoted path with space/script.py
+++ b/unquoted path with space/script.py
@@ -1 +1 @@
-foo
+bar
"""
    files = parse_unified_diff(diff_with_spaces)
    assert len(files) == 2
    assert files[0].file_path == "my directory/file name.py"
    assert files[0].additions == 1
    assert files[1].file_path == "unquoted path with space/script.py"
    assert files[1].additions == 1


def test_parse_no_newline_marker() -> None:
    """Verify '\\ No newline at end of file' does not disrupt line numbering."""
    files = parse_unified_diff(SAMPLE_NO_NEWLINE_DIFF)
    assert len(files) == 1

    file = files[0]
    assert len(file.hunks) == 1
    hunk = file.hunks[0]

    # Should only have 2 diff lines: '-' and '+'
    assert len(hunk.lines) == 2
    assert hunk.lines[0].origin == "-"
    assert hunk.lines[0].old_line_number == 1
    assert hunk.lines[1].origin == "+"
    assert hunk.lines[1].new_line_number == 1


def test_parse_malformed_and_edge_case_hunks() -> None:
    """Ensure malformed or truncated hunks do not crash the parser."""
    malformed_diff = """diff --git a/bad.py b/bad.py
index 1111..2222
--- a/bad.py
+++ b/bad.py
@@ -1,3 +1,3 @@
 random unexpected non-hunk line without diff prefix
+valid addition
@@ invalid hunk header
+another addition
"""
    files = parse_unified_diff(malformed_diff)
    assert len(files) == 1
    assert files[0].file_path == "bad.py"
    assert files[0].additions >= 1


# ---------------------------------------------------------------------------
# PRReviewer Heuristics & Report Tests
# ---------------------------------------------------------------------------

SAMPLE_PR_META = PullRequestMetadata(
    number=101,
    title="Add core feature",
    state="open",
    html_url="https://github.com/acme/project/pull/101",
    author="contributor1",
    base_branch="main",
    head_branch="feature",
    additions=20,
    deletions=5,
    changed_files=2,
    body="PR description here.",
)


def test_heuristic_diff_size_warning_and_compact_positive() -> None:
    """Verify large diff triggers a PR_HYGIENE warning and compact diff gets a positive note."""
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]

    # 1. Large diff: 600 additions
    large_files = [
        FileDiff(file_path="src/big.py", status="modified", additions=600, deletions=10)
    ]
    report_large = reviewer.evaluate(SAMPLE_PR_META, large_files)
    assert any(f.category == "PR_HYGIENE" and f.severity == "WARNING" for f in report_large.findings)
    assert "Large pull request detected" in report_large.formatted_markdown

    # 2. Compact diff: 50 lines across 2 files
    small_files = [
        FileDiff(file_path="src/a.py", status="modified", additions=30, deletions=5),
        FileDiff(file_path="src/b.py", status="modified", additions=15, deletions=0),
    ]
    report_small = reviewer.evaluate(SAMPLE_PR_META, small_files)
    assert not any(f.category == "PR_HYGIENE" for f in report_small.findings)
    assert any("Focused pull request size" in note for note in report_small.positive_notes)


def test_heuristic_test_accompaniment_warning_and_positive() -> None:
    """Verify warning when source code lacks tests, and positive note when tests are present."""
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]

    # Source code without tests
    no_tests = [
        FileDiff(file_path="src/service.py", status="added", additions=50, deletions=0)
    ]
    report_no_tests = reviewer.evaluate(SAMPLE_PR_META, no_tests)
    test_warnings = [f for f in report_no_tests.findings if f.category == "TESTING"]
    assert len(test_warnings) == 1
    assert "without accompanying test modifications" in test_warnings[0].message
    assert "In collaborative repositories, tests protect" in test_warnings[0].suggestion

    # Source code with tests
    with_tests = [
        FileDiff(file_path="src/service.py", status="added", additions=50, deletions=0),
        FileDiff(file_path="tests/test_service.py", status="added", additions=30, deletions=0),
    ]
    report_with_tests = reviewer.evaluate(SAMPLE_PR_META, with_tests)
    assert not any(f.category == "TESTING" for f in report_with_tests.findings)
    assert any("Automated test updates included" in note for note in report_with_tests.positive_notes)


def test_heuristic_doc_sync_info_and_positive() -> None:
    """Verify info finding when configs change without docs, and positive note when docs are updated."""
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]

    # Config updated without docs
    config_only = [
        FileDiff(file_path="pyproject.toml", status="modified", additions=10, deletions=2),
        FileDiff(file_path="tests/test_foo.py", status="added", additions=5, deletions=0),
    ]
    report_config = reviewer.evaluate(SAMPLE_PR_META, config_only)
    assert any(f.category == "DOCUMENTATION" and f.severity == "INFO" for f in report_config.findings)

    # Docs updated
    with_docs = [
        FileDiff(file_path="src/service.py", status="modified", additions=10, deletions=0),
        FileDiff(file_path="tests/test_service.py", status="modified", additions=10, deletions=0),
        FileDiff(file_path="docs/GUIDE.md", status="added", additions=20, deletions=0),
    ]
    report_docs = reviewer.evaluate(SAMPLE_PR_META, with_docs)
    assert not any(f.category == "DOCUMENTATION" for f in report_docs.findings)
    assert any("Documentation updated alongside" in note for note in report_docs.positive_notes)


def test_heuristic_code_smells_debug_residue() -> None:
    """Verify debug residue (print, breakpoint, debugger) is flagged with exact line numbers."""
    diff_with_debug = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,5 @@ def run():
     setup()
+    print("DEBUG: starting")
+    breakpoint()
     finish()
"""
    files = parse_unified_diff(diff_with_debug)
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]
    report = reviewer.evaluate(SAMPLE_PR_META, files)

    quality_findings = [f for f in report.findings if f.category == "CODE_QUALITY"]
    assert len(quality_findings) == 2
    assert quality_findings[0].file_path == "src/app.py"
    assert quality_findings[0].line_number == 11
    assert "Console print" in quality_findings[0].message
    assert quality_findings[1].line_number == 12
    assert "debugger/breakpoint" in quality_findings[1].message


def test_strict_secret_masking_and_no_leak() -> None:
    """CRITICAL SECURITY TEST: Ensure raw secrets are NEVER leaked into findings or reports."""
    raw_ghp = "ghp_TESTSECRETTOKEN1234567890abcdefghijkl"
    raw_password = "super_classified_password_xyz_12345"
    raw_aws = "AKIA1234567890ABCDEF"

    diff_with_secrets = f"""diff --git a/src/config.py b/src/config.py
--- a/src/config.py
+++ b/src/config.py
@@ -1,3 +1,6 @@
+token = "{raw_ghp}"
+password = "{raw_password}"
+aws_key = "{raw_aws}"
"""
    files = parse_unified_diff(diff_with_secrets)
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]
    report = reviewer.evaluate(SAMPLE_PR_META, files)

    # Verify findings are raised as CRITICAL SECURITY
    security_findings = [f for f in report.findings if f.category == "SECURITY"]
    assert len(security_findings) == 3
    assert all(f.severity == "CRITICAL" for f in security_findings)
    assert report.risk_level == "HIGH"

    # Stringify finding messages, suggestions, markdown, and JSON dump
    all_findings_text = " ".join(f.message + " " + f.suggestion for f in report.findings)
    markdown_output = report.formatted_markdown
    serialized_json = report.model_dump_json()

    # PROVE raw secret values NEVER appear in findings, markdown, or serialized JSON
    assert raw_ghp not in all_findings_text
    assert raw_ghp not in markdown_output
    assert raw_ghp not in serialized_json

    assert raw_password not in all_findings_text
    assert raw_password not in markdown_output
    assert raw_password not in serialized_json

    assert raw_aws not in all_findings_text
    assert raw_aws not in markdown_output
    assert raw_aws not in serialized_json


def test_finding_priority_order() -> None:
    """Verify findings are sorted deterministically: CRITICAL first, then WARNING, then INFO."""
    diff_mixed = """diff --git a/src/mixed.py b/src/mixed.py
--- a/src/mixed.py
+++ b/src/mixed.py
@@ -1,3 +1,5 @@
+print("debug")
+ghp_TOKEN1234567890abcdefghijklmnopqr
"""
    files = parse_unified_diff(diff_mixed)
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]
    report = reviewer.evaluate(SAMPLE_PR_META, files)

    severities = [f.severity for f in report.findings]
    # Expect CRITICAL first (secret), then WARNING (no tests), then INFO (print statement)
    assert severities[0] == "CRITICAL"
    assert "WARNING" in severities
    assert severities[-1] == "INFO"


def test_empty_and_binary_diff_reports() -> None:
    """Verify reports for empty diffs and binary files contain appropriate notices without crashing."""
    reviewer = PRReviewer(github_client=None)  # type: ignore[arg-type]

    # Empty diff
    report_empty = reviewer.evaluate(SAMPLE_PR_META, [])
    assert report_empty.files_analyzed == 0
    assert report_empty.risk_level == "LOW"
    assert "No textual code changes detected" in report_empty.formatted_markdown
    assert "Review Disclaimer" in report_empty.formatted_markdown

    # Binary diff
    binary_files = [FileDiff(file_path="logo.png", status="added", is_binary=True)]
    report_binary = reviewer.evaluate(SAMPLE_PR_META, binary_files)
    assert report_binary.files_analyzed == 1
    assert "contains only binary assets" in report_binary.formatted_markdown


@pytest.mark.anyio
async def test_full_async_review_pr() -> None:
    """Verify async review_pr fetches metadata and diff, and compiles report."""
    mock_pr = {
        "number": 88,
        "title": "Clean helper addition",
        "state": "open",
        "html_url": "https://github.com/acme/project/pull/88",
        "user": {"login": "alice"},
        "base": {"ref": "main"},
        "head": {"ref": "alice-patch"},
        "additions": 10,
        "deletions": 0,
        "changed_files": 2,
        "body": "Adds utility function.",
    }

    mock_diff = """diff --git a/src/utils.py b/src/utils.py
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,2 +1,6 @@
+def helper():
+    return True
diff --git a/tests/test_utils.py b/tests/test_utils.py
--- a/tests/test_utils.py
+++ b/tests/test_utils.py
@@ -1,2 +1,6 @@
+def test_helper():
+    assert helper() is True
"""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/acme/project/pulls/88":
            if request.headers.get("Accept") == "application/vnd.github.v3.diff":
                return httpx.Response(200, text=mock_diff)
            return httpx.Response(200, json=mock_pr)
        return httpx.Response(404, json={"message": "Not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        github_client = GitHubClient(client=http_client)
        reviewer = PRReviewer(github_client=github_client)

        report = await reviewer.review_pr("acme", "project", 88)

        assert isinstance(report, PRReviewReport)
        assert report.pr_number == 88
        assert report.author == "alice"
        assert report.risk_level == "LOW"
        assert report.files_analyzed == 2
        assert len(report.findings) == 0  # Clean PR with tests
        assert any("Automated test updates included" in note for note in report.positive_notes)
        assert "✨ No heuristic warnings or code smells detected!" in report.formatted_markdown
        assert "### ℹ️ Review Disclaimer" in report.formatted_markdown

