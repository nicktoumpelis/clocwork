import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from clocwork import analyse as an
from clocwork import cloc as cl
from clocwork import paths
from clocwork.sources import codex, gemini
from tests import repo_fixture as fx


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


class TestInheritedGitEnvironment(unittest.TestCase):
    """A GIT_DIR or GIT_WORK_TREE inherited from a hook or a wrapper names
    another repository; every git and cloc call must still read the one it
    was given."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(cls.tmp.name)
        cls.repo, cls.other = os.path.join(root, "myapp"), os.path.join(root, "other")
        for path, remote in ((cls.repo, "git@github.com:acme/myapp.git"), (cls.other, "git@github.com:acme/other.git")):
            os.makedirs(os.path.join(path, "Sources", "Core"))
            fx._write(path, "Sources/Core/main.swift", fx.SWIFT_V1)
            fx._git(path, "init", "-q", "-b", "main")
            fx._git(path, "remote", "add", "origin", remote)
            fx._git(path, "add", ".")
            fx._git(path, "commit", "-q", "-m", "Initial " + os.path.basename(path))
        os.makedirs(os.path.join(cls.other, "Elsewhere"))
        fx._write(cls.other, "Elsewhere/note.py", "print(1)\n")
        fx._git(cls.other, "add", ".")
        fx._git(cls.other, "commit", "-q", "-m", "Second")
        cls.head = fx._git(cls.repo, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def inherited(self):
        other_git = os.path.join(self.other, ".git")
        return mock.patch.dict(os.environ, {
            "GIT_DIR": other_git, "GIT_WORK_TREE": self.other, "GIT_COMMON_DIR": other_git,
            "GIT_INDEX_FILE": os.path.join(other_git, "index"),
            "GIT_OBJECT_DIRECTORY": os.path.join(other_git, "objects")})

    def test_the_environment_would_mislead_a_plain_git_call(self):
        # The premise: without the fix, git reads the other repository.
        with self.inherited():
            self.assertEqual(git(self.repo, "rev-parse", "--show-toplevel"), self.other)

    def test_paths_reads_the_given_repository(self):
        with self.inherited():
            self.assertEqual(paths.find_repo(os.path.join(self.repo, "Sources")), self.repo)
            self.assertEqual(paths.remote_key(self.repo), "github.com/acme/myapp")

    def test_analyse_reads_the_given_repository(self):
        with self.inherited():
            self.assertEqual(an.git(self.repo, "rev-parse", "HEAD").strip(), self.head)
            self.assertEqual([c["message"] for c in an.parse_log(self.repo, "main")], ["Initial myapp"])

    def test_sources_read_the_given_repository(self):
        with self.inherited():
            self.assertTrue(codex.commit_lookup(self.repo)(self.head))
            self.assertEqual(sorted(gemini.tracked_directories(self.repo)), ["Sources", "Sources/Core"])

    @unittest.skipUnless(shutil.which("cloc"), "cloc is not installed")
    def test_cloc_reads_the_given_repository(self):
        with self.inherited():
            self.assertEqual(cl.learn_extensions(self.repo, self.head), {"swift": "Swift"})
            self.assertEqual(set(cl.run_cloc(["--git", self.head], self.repo)) - {"header", "SUM"}, {"Swift"})

    def test_the_environment_drops_what_git_clears_for_another_repository(self):
        # git's own list, less the `git -c` settings it passes to a submodule.
        listed = git(self.repo, "rev-parse", "--local-env-vars").split()
        kept = {"GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"}
        with mock.patch.dict(os.environ, {name: "x" for name in listed}):
            env = paths.git_env(GIT_TERMINAL_PROMPT="0")
        self.assertEqual({name for name in listed if name in env}, kept)
        self.assertEqual((env["GIT_TERMINAL_PROMPT"], env["PATH"]), ("0", os.environ["PATH"]))


if __name__ == "__main__":
    unittest.main()
