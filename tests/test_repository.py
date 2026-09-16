"""Files that would be missing from what is published, though every test passes.

The Projects directory's global excludes file ignores `*claude*`, so a module
named after Claude Code is ignored unless this repository un-ignores it, and
`git add` of its directory skips it without a word. A package the build does
not list is left out of the wheel the same way. The suite runs from the
source tree either way, which is why each needs its own check.
"""

import fnmatch
import os
import subprocess
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What .gitignore and the maintainer's global excludes file mean to ignore
# there: caches, macOS and editor litter, and iCloud sync duplicates.
INTENDED = ("__pycache__", ".DS_Store", "._*", "*.swp", "*.egg-info", "* [0-9].*")


def intended(path):
    return any(fnmatch.fnmatch(part, pattern) for part in path.split("/") for pattern in INTENDED)


class TestNothingIsSilentlyIgnored(unittest.TestCase):
    def test_no_published_file_is_ignored_by_git(self):
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--",
             "src", "tests", "man", "clocwork", "README.md", "CHANGELOG.md", "pyproject.toml"],
            cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("not a git checkout")
        self.assertEqual([p for p in result.stdout.splitlines() if not intended(p)], [])


class TestEveryPackageIsBuilt(unittest.TestCase):
    def test_pyproject_lists_every_package_under_src(self):
        src = os.path.join(ROOT, "src")
        found = sorted(os.path.relpath(d, src).replace(os.sep, ".")
                       for d, _dirs, files in os.walk(src) if "__init__.py" in files)
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            listed = tomllib.load(f)["tool"]["setuptools"]["packages"]
        self.assertEqual(sorted(listed), found)


if __name__ == "__main__":
    unittest.main()
