"""Files git would silently leave out of a commit.

The Projects directory's global excludes file ignores `*claude*`, so a module
named after Claude Code is ignored unless this repository un-ignores it, and
`git add` of its directory skips it without a word. The suite still passes
on the machine that has the file, which is why this needs its own check.
"""

import fnmatch
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What .gitignore means to ignore under the published directories.
INTENDED = ("__pycache__", ".DS_Store", "*.egg-info", "* [0-9].*")


def intended(path):
    return any(fnmatch.fnmatch(part, pattern) for part in path.split("/") for pattern in INTENDED)


class TestNothingIsSilentlyIgnored(unittest.TestCase):
    def test_no_published_file_is_ignored_by_git(self):
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--",
             "src", "tests", "man", "clocwork", "README.md", "pyproject.toml"],
            cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual([p for p in result.stdout.splitlines() if not intended(p)], [])


if __name__ == "__main__":
    unittest.main()
