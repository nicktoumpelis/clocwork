"""The suite runs git in temporary repositories, and the user's own git
configuration must not reach them: a global pre-commit hook or signing
setting would fail every commit a fixture makes."""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestGitConfigIsolation(unittest.TestCase):
    def test_git_reads_only_the_repository_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            scopes = subprocess.run(["git", "config", "--list", "--show-scope"], cwd=d, check=True,
                                    capture_output=True, text=True).stdout.splitlines()
        self.assertEqual([s for s in scopes if not s.startswith("local\t")], [])

    def test_an_inherited_global_hook_does_not_run(self):
        with tempfile.TemporaryDirectory() as d:
            marker = os.path.join(d, "hook-ran")
            hooks = os.path.join(d, "hooks")
            os.makedirs(hooks)
            hook = os.path.join(hooks, "pre-commit")
            with open(hook, "w") as f:
                f.write(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
            os.chmod(hook, 0o755)
            config = os.path.join(d, "gitconfig")
            with open(config, "w") as f:
                f.write(f"[core]\n\thooksPath = {hooks}\n")
            repo = os.path.join(d, "repo")
            subprocess.run(["git", "init", "-q", repo], check=True)
            commit = ["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c"]

            # A process that imports the test package, started with the
            # hostile file as its global configuration, commits unhindered.
            child = ("import subprocess, sys, tests; "
                     f"sys.exit(subprocess.run({commit!r}, cwd={repo!r}).returncode)")
            env = dict(os.environ, GIT_CONFIG_GLOBAL=config)
            env.pop("GIT_CONFIG_NOSYSTEM", None)
            result = subprocess.run([sys.executable, "-c", child], cwd=ROOT, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(os.path.exists(marker))

            # The premise: git itself, reading that file, runs the hook and fails.
            result = subprocess.run(commit, cwd=repo, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(os.path.exists(marker))
