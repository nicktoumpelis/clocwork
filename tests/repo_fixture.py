# tests/repo_fixture.py
"""Builds a tiny git repository with known line counts for the analyser tests.

Commit 1 "Initial":   App/main.swift (3 code, 2 comment, 1 blank), README.md (2 code, 1 blank)
Commit 2 "Add tests": App/main.swift +1 comment; Tests/AppTests.swift (2 code, 1 comment); Claude trailer
Commit 3 "Notes":     Notes.md (1 code) on branch feature
Commit 4:             merge of feature, subject "Merge pull request #1 from x/feature"
"""
import os
import subprocess

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
