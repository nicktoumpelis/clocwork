# tests/repo_fixture.py
"""Builds a tiny git repository with known line counts for the analyser tests.

Commit 1 "Initial":   App/main.swift (3 code, 2 comment, 1 blank), README.md (2 code, 1 blank)
Commit 2 "Add tests": App/main.swift +1 comment; Tests/AppTests.swift (2 code, 1 comment); Claude trailer
Commit 3 "Notes":     Notes.md (1 code) on branch feature
Commit 4:             merge of feature, subject "Merge pull request #1 from x/feature"
"""
import json
import os
import subprocess
import tempfile

SWIFT_V1 = "import Foundation\n\n// helper\nfunc a() {}\n/// doc\nfunc b() {}\n"
SWIFT_V2 = SWIFT_V1 + "// more\n"
README = "# Title\n\nSome text\n"
TEST_SWIFT = "import XCTest\n// test\nfinal class T {}\n"
NOTES = "note\n"

SWIFT_ROW_1 = [3, 0, 2, 0, 1, 0]
MARKDOWN_ROW_1 = [2, 0, 0, 0, 1, 0]
SWIFT_ROW_2 = [2, 0, 2, 0, 0, 0]        # tests file + one comment appended to main.swift
SWIFT_TEST_ROW_2 = [2, 0, 1, 0, 0, 0]
MARKDOWN_ROW_3 = [1, 0, 0, 0, 0, 0]

HEAD_SWIFT = {"code": 5, "comment": 4, "blank": 1}
HEAD_MARKDOWN = {"code": 3, "comment": 0, "blank": 1}
HEAD_TEST_SWIFT = {"code": 2, "comment": 1, "blank": 0}


def _git(repo, *args, date="2025-01-01T10:00:00+00:00"):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@example.com",
               GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", "-c", "commit.gpgsign=false"] + list(args),
                          cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _write(repo, rel, text):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


def make_repo(root):
    _git(root, "init", "-q", "-b", "main")
    _write(root, "App/main.swift", SWIFT_V1)
    _write(root, "README.md", README)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Initial", date="2025-01-01T10:00:00+00:00")

    _write(root, "App/main.swift", SWIFT_V2)
    _write(root, "Tests/AppTests.swift", TEST_SWIFT)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Add tests\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>",
         date="2025-01-02T10:00:00+00:00")

    _git(root, "checkout", "-q", "-b", "feature")
    _write(root, "Notes.md", NOTES)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Notes", date="2025-01-03T10:00:00+00:00")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #1 from x/feature",
         date="2025-01-04T10:00:00+00:00")

    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


EXTRA = "extra\n"


def add_branch_merge(root):
    """Add a fifth and sixth commit: Extra.md on branch feature2, merged with a non-PR subject.
    Returns [feature2_commit, merge_commit] full hashes."""
    _git(root, "checkout", "-q", "-b", "feature2")
    _write(root, "Extra.md", EXTRA)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Extra", date="2025-01-05T10:00:00+00:00")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--no-ff", "feature2", "-m", "Merge branch 'feature2' into main",
         date="2025-01-06T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()[-2:]


GO = "package pkg\n\n// Serve serves.\nfunc Serve() {}\n"
GO_TEST = "package pkg\n\nimport \"testing\"\n\nfunc TestServe(t *testing.T) {}\n"
PY = "def run():\n    # work\n    return 1\n"
PY_TEST = "from src.app import run\n\n\ndef test_run():\n    assert run() == 1\n"
JS = "export function app() { return 1; }\n"
JS_TEST = "import { app } from './app';\ntest('app', () => expect(app()).toBe(1));\n"
JAVA = "public class A {\n    // main\n    public static void main(String[] a) {}\n}\n"
JAVA_TEST = "public class ATest {\n    public void testA() {}\n}\n"


def make_polyglot_repo(root):
    """Go, Python, JavaScript and Java with each ecosystem's test convention and
    three different agent trailers. No Xcode-style Tests/ directory anywhere,
    so nothing here matches the rule the Swift fixture relies on."""
    _git(root, "init", "-q", "-b", "main")
    _write(root, "pkg/server.go", GO)
    _write(root, "pkg/server_test.go", GO_TEST)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Go\n\nCo-Authored-By: GitHub Copilot <copilot@github.com>",
         date="2025-02-01T10:00:00+00:00")
    _write(root, "src/app.py", PY)
    _write(root, "tests/test_app.py", PY_TEST)
    _write(root, "web/app.js", JS)
    _write(root, "web/app.test.js", JS_TEST)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Python and JS\n\nCo-Authored-By: Cursor <cursor@cursor.com>",
         date="2025-02-02T10:00:00+00:00")
    _write(root, "src/main/java/A.java", JAVA)
    _write(root, "src/test/java/ATest.java", JAVA_TEST)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Java\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>",
         date="2025-02-03T10:00:00+00:00")
    _write(root, "docs/notes.md", "# Notes\n")
    _git(root, "add", ".")
    # An agent no built-in rule knows: attributed only when [agents].extra names it.
    _git(root, "commit", "-q", "-m", "Notes\n\nCo-Authored-By: Jules <jules@google.com>",
         date="2025-02-04T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


# Files cloc names by filename or shebang rather than by extension, with the
# language cloc 2.10 gives each. Two lines of code apiece.
EXTENSIONLESS = {
    "Dockerfile": ("FROM alpine\nRUN true\n", "Dockerfile"),
    "Makefile": ("all:\n\ttrue\n", "make"),
    "bin/run": ("#!/bin/sh\necho hi\n", "Bourne Shell"),
    "tool": ("#!/usr/bin/env python3\nprint(1)\n", "Python"),
}


def make_extensionless_repo(root):
    """One commit adding the EXTENSIONLESS files, then one editing the shell script."""
    _git(root, "init", "-q", "-b", "main")
    for rel, (text, _) in EXTENSIONLESS.items():
        _write(root, rel, text)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Initial", date="2025-01-01T10:00:00+00:00")
    _write(root, "bin/run", EXTENSIONLESS["bin/run"][0] + "echo again\n")
    _git(root, "commit", "-q", "-am", "Say it twice", date="2025-01-02T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


def make_renamed_repo(root):
    """Files renamed during the history, which cloc reports under their old
    names: a shell script renamed twice (the second time with an edit), and a
    text file renamed to Markdown."""
    _git(root, "init", "-q", "-b", "main")
    _write(root, "old", "#!/bin/sh\necho a\necho b\n")
    _write(root, "notes.txt", "one\ntwo\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Initial", date="2025-01-01T10:00:00+00:00")
    _git(root, "mv", "old", "middle")
    _git(root, "mv", "notes.txt", "notes.md")
    _git(root, "commit", "-q", "-m", "Rename", date="2025-01-02T10:00:00+00:00")
    _write(root, "middle", "#!/bin/sh\necho a\necho b\necho c\n")
    os.makedirs(os.path.join(root, "bin"))
    _git(root, "mv", "middle", "bin/final")
    _git(root, "commit", "-q", "-am", "Move and extend", date="2025-01-03T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


# Files cloc names against their extension, with the language cloc 2.10 gives
# each: CMake by filename, and .cgi scripts by shebang. Two lines apiece.
NAMED_AGAINST_EXTENSION = {
    "CMakeLists.txt": ("cmake_minimum_required(VERSION 3.20)\nproject(MyApp)\n", "CMake"),
    "notes.txt": ("one\ntwo\n", "Text"),
    "cgi/a.cgi": ("#!/usr/bin/perl\nprint 1;\n", "Perl"),
    "cgi/b.cgi": ("#!/usr/bin/perl\nprint 2;\n", "Perl"),
    "cgi/odd.cgi": ("#!/usr/bin/env python3\nprint(3)\n", "Python"),
}


def make_named_against_extension_repo(root, order=None):
    """One commit per NAMED_AGAINST_EXTENSION file, in `order` (its keys)."""
    _git(root, "init", "-q", "-b", "main")
    for i, rel in enumerate(order or NAMED_AGAINST_EXTENSION):
        _write(root, rel, NAMED_AGAINST_EXTENSION[rel][0])
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "Add " + rel, date=f"2025-01-{i + 1:02d}T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


def make_identical_files_repo(root):
    """Identical copies, with and without an extension, in one commit."""
    _git(root, "init", "-q", "-b", "main")
    for rel in ("a.py", "t/b.py"):
        _write(root, rel, "x = 1\ny = 2\n")
    for rel in ("bin/one", "bin/two"):
        _write(root, rel, "#!/bin/sh\necho same\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Copies", date="2025-01-01T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


def make_recreated_name_repo(root):
    """notes.txt renamed to notes.md, then a new notes.txt: the old name is
    present again at HEAD, as a Text file."""
    _git(root, "init", "-q", "-b", "main")
    _write(root, "notes.txt", "one\ntwo\nthree\nfour\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Notes", date="2025-01-01T10:00:00+00:00")
    _git(root, "mv", "notes.txt", "notes.md")
    _git(root, "commit", "-q", "-m", "To Markdown", date="2025-01-02T10:00:00+00:00")
    _write(root, "notes.txt", "five\nsix\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "New notes", date="2025-01-03T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


PAGE = ".. a comment\n.. another\n\nText line one\nText line two\n"


def cloc_count(name, text):
    """(counts, language) that the cloc on PATH gives `text` in a file named
    `name`, or (None, None). cloc versions name some files differently: an
    .inc page is BitBake to 2.10 and Fortran 77 to 2.06."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, name), "w") as f:
            f.write(text)
        out = subprocess.run(["cloc", "--quiet", "--json", "--by-file", name], cwd=d,
                             capture_output=True, text=True, check=True).stdout
    entry = json.loads(out).get(name) if out.strip() else None
    if not entry:
        return None, None
    return {t: entry[t] for t in ("code", "comment", "blank")}, entry["language"]


def make_language_change_repo(root):
    """Renames whose sides cloc counts differently: a reStructuredText page
    with two comment lines renamed to .inc (all code to cloc) and later
    deleted, and a file cloc does not count renamed, with an edit, to
    Python."""
    _git(root, "init", "-q", "-b", "main")
    _write(root, "docs/contents.rst", PAGE)
    _write(root, "tool.xyz", "x = 1\ny = 2\n")
    _write(root, "keep.md", "# Keep\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Pages", date="2025-01-01T10:00:00+00:00")
    _git(root, "mv", "docs/contents.rst", "docs/contents.inc")
    _git(root, "mv", "tool.xyz", "tool.py")
    _write(root, "tool.py", "x = 1\ny = 2\nz = 3\n")
    _git(root, "commit", "-q", "-am", "Rename", date="2025-01-02T10:00:00+00:00")
    _git(root, "rm", "-q", "docs/contents.inc")
    _git(root, "commit", "-q", "-m", "Drop the page", date="2025-01-03T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()


def make_symlink_repo(root):
    """A Markdown file, a symlink to it, and a symlink to a directory."""
    _git(root, "init", "-q", "-b", "main")
    _write(root, "AGENTS.md", "# Agents\n\nRead this.\n")
    _write(root, "src/app.py", "x = 1\n")
    os.symlink("AGENTS.md", os.path.join(root, "LINK.md"))
    os.symlink("src", os.path.join(root, "lib"))
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "Links", date="2025-01-01T10:00:00+00:00")
    return _git(root, "log", "--reverse", "--format=%H", "main").splitlines()
