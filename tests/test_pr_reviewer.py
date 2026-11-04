"""Unit tests for the unified diff parser engine."""

import pytest
from src.guardian.modules.pr_reviewer import (
    DiffHunk,
    DiffLine,
    FileDiff,
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
