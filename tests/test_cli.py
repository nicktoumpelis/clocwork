import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr

from clocwork import cli
from tests import repo_fixture as fx

HAVE_CLOC = shutil.which("cloc") is not None


class TestParseArgs(unittest.TestCase):
    def test_bare_is_run(self):
        a = cli.parse_args([])
        self.assertEqual((a.command, a.repo), ("run", None))

    def test_path_first_is_run_with_repo(self):
        a = cli.parse_args(["/tmp/x", "--no-open"])
        self.assertEqual((a.command, a.repo, a.no_open), ("run", "/tmp/x", True))

    def test_subcommands(self):
        self.assertEqual(cli.parse_args(["tokens", "/tmp/x"]).command, "tokens")
        self.assertEqual(cli.parse_args(["tokens", "/tmp/x"]).repo, "/tmp/x")
        a = cli.parse_args(["render", "-o", "/ws"])
        self.assertEqual((a.command, a.output, a.repo), ("render", "/ws", None))

    def test_render_requires_a_workspace(self):
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                cli.parse_args(["render"])

    def test_tokens_rejects_the_page_options_it_would_ignore(self):
        for flag in (["--no-open"], ["--locale", "en-SE"], ["--config", "x.toml"]):
            with self.subTest(flag=flag):
                with self.assertRaises(SystemExit):
                    with redirect_stderr(io.StringIO()):
                        cli.parse_args(["tokens", "/tmp/x"] + flag)

    def test_options(self):
        a = cli.parse_args(["--branch", "dev", "--max-commits", "5", "--cache-dir", "/c",
                            "--config", "/f.toml", "--locale", "en-SE", "-q"])
        self.assertEqual((a.branch, a.max_commits, a.cache_dir, a.config, a.locale, a.quiet),
                         ("dev", 5, "/c", "/f.toml", "en-SE", True))

    def test_negative_max_commits_is_rejected(self):
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                cli.parse_args(["--max-commits", "-1"])

    def test_run_only_options_default_on_other_commands(self):
        a = cli.parse_args(["render", "-o", "/ws"])
        self.assertEqual((a.branch, a.max_commits, a.no_tokens, a.cache_dir), (None, None, False, None))


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.root, "poly")
        os.makedirs(self.repo)
        fx.make_polyglot_repo(self.repo)
        self.ws = os.path.join(self.root, "poly-stats")
        self.cache = os.path.join(self.root, "cache")
        self.projects = os.path.join(self.root, "projects")   # no transcripts in here
        os.makedirs(self.projects)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        quiet = ["-q"] if args[0] == "tokens" else ["--no-open", "-q"]   # tokens has no page to open
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(list(args) + quiet, projects_dir=self.projects)
        return code, err.getvalue()

    def test_full_run_into_the_sibling_workspace(self):
        code, err = self.run_cli(self.repo, "--cache-dir", self.cache)
        self.assertEqual((code, err), (0, ""))
        for name in ("index.html", "commit_bodies.js", "full_commit_data.json", "clocwork.json"):
            self.assertTrue(os.path.exists(os.path.join(self.ws, name)), name)
        with open(os.path.join(self.ws, "index.html")) as f:
            page = f.read()
        for p in ("__TITLE__", "__REPO_NAME__", "__DATA__", "__ANNOTATIONS__"):
            self.assertNotIn(p, page)
        self.assertIn("<h1><span>poly</span>", page)
        with open(os.path.join(self.ws, "full_commit_data.json")) as f:
            data = json.load(f)
        self.assertEqual(set(data["first_appearances"]), {"Copilot", "Cursor", "Claude Opus 4.6"})
        self.assertEqual(set(data["summary"]["head_snapshot"]["tests"]), {"Go", "Python", "JavaScript", "Java"})
        self.assertIsNone(data["summary"]["repo_url"])       # no remote: links omitted, not broken
        keys = os.listdir(self.cache)
        self.assertEqual(len(keys), 1)
        self.assertTrue(keys[0].startswith("poly-"))
        self.assertTrue(os.path.exists(os.path.join(self.cache, keys[0], "cloc_cache.json")))

    def test_title_from_config_in_the_repository(self):
        with open(os.path.join(self.repo, ".clocwork.toml"), "w") as f:
            f.write('title = "Poly Project"\n')
        self.assertEqual(self.run_cli(self.repo, "--cache-dir", self.cache)[0], 0)
        with open(os.path.join(self.ws, "index.html")) as f:
            self.assertIn("<title>Poly Project - Full Commit History</title>", f.read())

    def test_tokens_without_transcripts_is_not_an_error(self):
        self.assertEqual(self.run_cli("tokens", self.repo), (0, ""))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "clocwork.json")))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "token_usage.json")))

    def test_render_needs_no_repository(self):
        self.assertEqual(self.run_cli(self.repo, "--cache-dir", self.cache)[0], 0)
        os.remove(os.path.join(self.ws, "index.html"))
        shutil.rmtree(self.repo)
        self.assertEqual(self.run_cli("render", "-o", self.ws), (0, ""))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "index.html")))

    def test_render_before_any_analysis_is_an_error_not_a_traceback(self):
        self.assertEqual(self.run_cli("tokens", self.repo), (0, ""))     # identity file, no data yet
        code, err = self.run_cli("render", "-o", self.ws)
        self.assertEqual(code, 2)
        self.assertIn("full_commit_data.json", err)

    def test_corrupt_analysis_file_is_an_error_not_a_traceback(self):
        self.assertEqual(self.run_cli(self.repo, "--cache-dir", self.cache)[0], 0)
        with open(os.path.join(self.ws, "full_commit_data.json"), "w") as f:
            f.write("{not json")
        code, err = self.run_cli("render", "-o", self.ws)
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_render_refuses_a_directory_that_is_not_a_workspace(self):
        code, err = self.run_cli("render", "-o", self.root)
        self.assertEqual(code, 2)
        self.assertIn("clocwork.json", err)

    def test_mismatched_workspace_is_refused(self):
        self.assertEqual(self.run_cli(self.repo, "--cache-dir", self.cache)[0], 0)
        other = os.path.join(self.root, "other")
        os.makedirs(other)
        fx.make_repo(other)
        code, err = self.run_cli(other, "-o", self.ws, "--cache-dir", self.cache)
        self.assertEqual(code, 2)
        self.assertIn("-o", err)

    def test_not_a_repository(self):
        code, err = self.run_cli(self.root, "--cache-dir", self.cache)
        self.assertEqual(code, 2)
        self.assertIn(self.root, err)

    def test_invalid_config_names_the_file(self):
        bad = os.path.join(self.root, "bad.toml")
        with open(bad, "w") as f:
            f.write("[tests\n")
        code, err = self.run_cli(self.repo, "--config", bad, "--cache-dir", self.cache)
        self.assertEqual(code, 2)
        self.assertIn("bad.toml", err)

    def test_subdirectory_resolves_to_the_repository(self):
        self.assertEqual(self.run_cli(os.path.join(self.repo, "pkg"), "--cache-dir", self.cache)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(self.ws, "index.html")))

    def test_explicit_workspace_and_no_tokens(self):
        ws = os.path.join(self.root, "elsewhere")
        self.assertEqual(self.run_cli(self.repo, "-o", ws, "--no-tokens", "--cache-dir", self.cache)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(ws, "index.html")))
        self.assertFalse(os.path.exists(self.ws))


if __name__ == "__main__":
    unittest.main()
