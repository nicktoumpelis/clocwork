"""The suite runs git in temporary repositories, and the user's own git
configuration must not reach them: a global pre-commit hook or signing
setting would fail every commit a fixture makes."""

import os
import subprocess
import tempfile
import unittest


class TestGitConfigIsolation(unittest.TestCase):
    def test_git_reads_no_global_or_system_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            scopes = subprocess.run(["git", "config", "--list", "--show-scope"], cwd=d, check=True,
                                    capture_output=True, text=True).stdout.splitlines()
        # "unknown" is a configuration built into the git binary (Apple's
        # git has one); only the user's and the machine's files are shut out.
        self.assertEqual([s for s in scopes if s.split("\t")[0] in ("global", "system")], [])

    def test_a_global_hook_does_not_run(self):
        # The environment tests/__init__.py sets wins over a GIT_CONFIG_GLOBAL
        # the suite inherited, so a hostile file named there is never read.
        with tempfile.TemporaryDirectory() as d:
            hooks = os.path.join(d, "hooks")
            os.makedirs(hooks)
            hook = os.path.join(hooks, "pre-commit")
            with open(hook, "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(hook, 0o755)
            config = os.path.join(d, "gitconfig")
            with open(config, "w") as f:
                f.write(f"[core]\n\thooksPath = {hooks}\n")
            repo = os.path.join(d, "repo")
            subprocess.run(["git", "init", "-q", repo], check=True)
            env = dict(os.environ)
            self.assertEqual(env.get("GIT_CONFIG_GLOBAL"), os.devnull)
            result = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q",
                                     "--allow-empty", "-m", "c"], cwd=repo, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # The premise: the same commit with the file read as global config fails.
            env["GIT_CONFIG_GLOBAL"] = config
            result = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@t", "commit", "-q",
                                     "--allow-empty", "-m", "c"], cwd=repo, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
