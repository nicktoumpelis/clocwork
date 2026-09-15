import json
import os
import subprocess
import tempfile
import unittest

from clocwork import paths


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class TestFindRepo(unittest.TestCase):
    def test_from_subdirectory(self):
        with tempfile.TemporaryDirectory() as d:
            real = os.path.realpath(d)
            git(real, "init", "-q")
            sub = os.path.join(real, "a", "b")
            os.makedirs(sub)
            self.assertEqual(paths.find_repo(sub), real)

    def test_not_a_repo_names_the_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(paths.NotARepository) as ctx:
                paths.find_repo(d)
            self.assertIn(os.path.abspath(d), str(ctx.exception))

    def test_missing_directory(self):
        with self.assertRaises(paths.NotARepository):
            paths.find_repo("/no/such/directory/anywhere")


class TestWorkspaceAndCache(unittest.TestCase):
    def test_default_workspace_is_a_sibling(self):
        self.assertEqual(paths.default_workspace("/code/myapp"), "/code/myapp-stats")
        self.assertEqual(paths.default_workspace("/code/myapp/"), "/code/myapp-stats")

    def test_cache_key_is_readable_and_stable(self):
        k = paths.cache_key("/code/myapp")
        self.assertTrue(k.startswith("myapp-"))
        self.assertEqual(len(k), len("myapp-") + 12)
        self.assertEqual(k, paths.cache_key("/code/myapp"))
        self.assertNotEqual(k, paths.cache_key("/other/myapp"))

    def test_cache_key_does_not_depend_on_the_claude_encoding(self):
        # If the cache were keyed by Claude Code's scheme, an upstream change to
        # that scheme would relocate every cache directory.
        before = paths.cache_key("/code/myapp")
        original = paths.claude_project_dir
        paths.claude_project_dir = lambda repo: "changed-upstream-" + original(repo)
        try:
            self.assertEqual(paths.cache_key("/code/myapp"), before)
        finally:
            paths.claude_project_dir = original
        self.assertNotIn(original("/code/myapp"), before)

    def test_claude_project_dir(self):
        self.assertEqual(paths.claude_project_dir("/Users/nick/Library/Mobile Documents/com~apple~CloudDocs/MyApp"),
                         "-Users-nick-Library-Mobile-Documents-com-apple-CloudDocs-MyApp")
        self.assertEqual(paths.claude_project_dir("/tmp/Repo"), "-tmp-Repo")

    def test_cache_root_precedence(self):
        self.assertEqual(paths.cache_root("/x"), "/x")
        self.assertEqual(paths.cache_root(None, env={"XDG_CACHE_HOME": "/xdg"}), "/xdg/clocwork")
        self.assertEqual(paths.cache_root(None, env={}), os.path.expanduser("~/.cache/clocwork"))

    def test_cache_path(self):
        self.assertEqual(paths.cache_path("/code/myapp", "/x"),
                         os.path.join("/x", paths.cache_key("/code/myapp"), "cloc_cache.json"))


class TestRemoteUrl(unittest.TestCase):
    def check(self, remote, want):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            if remote:
                git(d, "remote", "add", "origin", remote)
            self.assertEqual(paths.remote_url(d), want)

    def test_github_ssh_and_https(self):
        self.check("git@github.com:x/y.git", "https://github.com/x/y")
        self.check("https://github.com/x/y", "https://github.com/x/y")
        self.check("ssh://git@github.com/x/y.git", "https://github.com/x/y")

    def test_gitlab_and_bitbucket(self):
        self.check("git@gitlab.com:x/y.git", "https://gitlab.com/x/y")
        self.check("https://bitbucket.org/x/y.git", "https://bitbucket.org/x/y")
        self.check("https://gitlab.com/group/sub/repo.git", "https://gitlab.com/group/sub/repo")

    def test_host_case_user_prefix_and_port(self):
        self.check("https://GitHub.com/x/y", "https://github.com/x/y")
        self.check("https://user:token@github.com/x/y.git", "https://github.com/x/y")
        self.check("ssh://github.com:22/x/y.git", "https://github.com/x/y")

    def test_unknown_host_and_no_remote(self):
        self.check("git@example.com:x/y.git", None)
        self.check(None, None)

    def test_parse_remote_forms(self):
        self.assertEqual(paths.parse_remote("git@example.com:x/y.git"), ("example.com", "x/y"))
        self.assertEqual(paths.parse_remote("ssh://git@example.com/x/y"), ("example.com", "x/y"))
        self.assertEqual(paths.parse_remote("https://example.com/x/y/"), ("example.com", "x/y"))
        self.assertIsNone(paths.parse_remote("not a remote"))
        self.assertIsNone(paths.parse_remote("/local/path"))
        self.assertIsNone(paths.parse_remote("https://github.com/x"))     # no owner/name


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "remote", "add", "origin", "git@github.com:x/repo.git")
        self.ws = os.path.join(self.tmp.name, "repo-stats")

    def tearDown(self):
        self.tmp.cleanup()

    def other_repo(self, name, remote):
        other = os.path.join(self.tmp.name, name)
        os.makedirs(other)
        git(other, "init", "-q")
        if remote:
            git(other, "remote", "add", "origin", remote)
        return other

    def test_first_run_creates_the_workspace_and_writes_the_file(self):
        ident = paths.check_identity(self.ws, self.repo, "0.1.0")
        with open(os.path.join(self.ws, paths.IDENTITY_FILE)) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["repo_remote"], "https://github.com/x/repo")
        self.assertEqual(on_disk["repo_name"], "repo")
        self.assertEqual(on_disk["version"], "0.1.0")
        self.assertEqual(ident, on_disk)

    def test_same_repo_by_remote_passes_even_from_another_path(self):
        paths.check_identity(self.ws, self.repo, "0.1.0")
        clone = self.other_repo("clone", "https://github.com/x/repo")
        self.assertEqual(paths.check_identity(self.ws, clone, "0.1.0")["repo_name"], "repo")

    def test_other_repo_is_refused_naming_both(self):
        paths.check_identity(self.ws, self.repo, "0.1.0")
        other = self.other_repo("other", "git@github.com:x/other.git")
        with self.assertRaises(paths.WorkspaceMismatch) as ctx:
            paths.check_identity(self.ws, other, "0.1.0")
        message = str(ctx.exception)
        self.assertIn("x/repo", message)
        self.assertIn("x/other", message)
        self.assertIn("-o", message)

    def test_path_is_the_fallback_without_a_remote(self):
        git(self.repo, "remote", "remove", "origin")
        paths.check_identity(self.ws, self.repo, "0.1.0")
        other = self.other_repo("other", None)
        with self.assertRaises(paths.WorkspaceMismatch):
            paths.check_identity(self.ws, other, "0.1.0")

    def test_read_identity_of_a_plain_directory_is_none(self):
        os.makedirs(self.ws)
        self.assertIsNone(paths.read_identity(self.ws))

    def test_unknown_host_still_guards_by_remote(self):
        # A self-hosted remote gets no commit links but still an identity, so a
        # second checkout of the same repository is recognised.
        git(self.repo, "remote", "set-url", "origin", "git@git.example.com:team/repo.git")
        ident = paths.check_identity(self.ws, self.repo, "0.1.0")
        self.assertEqual(ident["repo_remote"], "git.example.com/team/repo")
        clone = self.other_repo("clone", "https://git.example.com/team/repo")
        paths.check_identity(self.ws, clone, "0.1.0")   # no raise
        other = self.other_repo("other", "https://git.example.com/team/other")
        with self.assertRaises(paths.WorkspaceMismatch):
            paths.check_identity(self.ws, other, "0.1.0")

    def test_corrupt_or_incomplete_identity_is_an_error_not_a_traceback(self):
        os.makedirs(self.ws)
        path = os.path.join(self.ws, paths.IDENTITY_FILE)
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(paths.WorkspaceMismatch):
            paths.read_identity(self.ws)
        with open(path, "w") as f:
            f.write('{"version": "0.1.0"}')
        with self.assertRaises(paths.WorkspaceMismatch):
            paths.check_identity(self.ws, self.repo, "0.1.0")


if __name__ == "__main__":
    unittest.main()
