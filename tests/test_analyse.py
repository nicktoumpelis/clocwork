import json
import os
import shutil
import tempfile
import unittest

import analyse_all_commits as an
from tests import repo_fixture as fx

HAVE_CLOC = shutil.which("cloc") is not None


class TestParseLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_commits_in_history_order_with_parents(self):
        commits = an.parse_log(self.tmp.name, "main")
        self.assertEqual([c["hash"] for c in commits], self.hashes)
        self.assertEqual(commits[0]["parents"], [])
        self.assertEqual(commits[1]["parents"], [self.hashes[0]])
        self.assertEqual(commits[3]["parents"][0], self.hashes[1])   # merge's first parent is main
        self.assertEqual(len(commits[3]["parents"]), 2)

    def test_agent_and_message(self):
        commits = an.parse_log(self.tmp.name, "main")
        self.assertEqual(commits[1]["agent"], "Claude Opus 4.6")
        self.assertIsNone(commits[0]["agent"])
        self.assertEqual(commits[3]["message"], "Merge pull request #1 from x/feature")
        self.assertEqual(commits[0]["date"][:10], "2025-01-01")


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestAnalyse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)
        cls.out = os.path.join(cls.tmp.name, "out.json")
        cls.cache = os.path.join(cls.tmp.name, "cache.json")
        cls.data = an.analyse(cls.tmp.name, cls.out, cls.cache, log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_languages_ordered_by_code_at_head(self):
        self.assertEqual(self.data["languages"], ["Swift", "Markdown"])

    def test_per_commit_matrices(self):
        c = self.data["commits"]
        self.assertEqual(c[0]["lines"], {"Swift": fx.SWIFT_ROW_1, "Markdown": fx.MARKDOWN_ROW_1})
        self.assertEqual(c[0]["test_lines"], {})
        self.assertEqual(c[1]["lines"], {"Swift": fx.SWIFT_ROW_2})
        self.assertEqual(c[1]["test_lines"], {"Swift": fx.SWIFT_TEST_ROW_2})
        self.assertEqual(c[2]["lines"], {"Markdown": fx.MARKDOWN_ROW_3})
        self.assertEqual(c[3]["lines"], {})
        self.assertEqual([x["status"] for x in c], ["ok", "ok", "ok", "merge"])
        self.assertEqual(c[3]["agent"], "Misc")
        self.assertNotIn("swift_delta", c[0])

    def test_snapshot_and_reconciliation(self):
        s = self.data["summary"]
        self.assertEqual(s["head_snapshot"]["all"], {"Swift": fx.HEAD_SWIFT, "Markdown": fx.HEAD_MARKDOWN})
        self.assertEqual(s["head_snapshot"]["tests"], {"Swift": fx.HEAD_TEST_SWIFT})
        self.assertEqual(s["running_totals"]["all"], s["head_snapshot"]["all"])
        zero = {"code": 0, "comment": 0, "blank": 0}
        self.assertEqual(s["reconciliation"], {"Swift": zero, "Markdown": zero})
        self.assertEqual(s["mapping_check"], {"Swift": zero, "Markdown": zero})
        self.assertEqual(s["unmeasured_commits"], 0)
        self.assertEqual(s["pending_commits"], 0)

    def test_counts_and_legacy_keys_removed(self):
        self.assertEqual(self.data["summary"]["misc_commits"], 1)
        self.assertEqual(self.data["summary"]["ai_assisted_commits"], 1)
        self.assertEqual(self.data["summary"]["human_only_commits"], 2)
        for key in ("daily", "biggest_gains", "biggest_drops", "agent_stats"):
            self.assertNotIn(key, self.data)
        self.assertEqual(self.data["first_appearances"]["Claude Opus 4.6"]["hash"], self.hashes[1][:7])
        with open(self.out) as f:
            self.assertEqual(json.load(f)["languages"], ["Swift", "Markdown"])

    def test_cache_is_written_and_reused(self):
        with open(self.cache) as f:
            cache = json.load(f)
        self.assertEqual(sorted(cache["commits"]), sorted(self.hashes[:3]))
        calls = []
        original = an.cl.diff_commit
        an.cl.diff_commit = lambda *a, **k: calls.append(a) or original(*a, **k)
        try:
            an.analyse(self.tmp.name, self.out, self.cache, log=lambda *a: None)
        finally:
            an.cl.diff_commit = original
        self.assertEqual(calls, [])

    def test_cap_marks_pending(self):
        with tempfile.TemporaryDirectory() as d:
            hashes = fx.make_repo(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), max_commits=1, log=lambda *a: None)
            self.assertEqual([c["status"] for c in data["commits"]], ["ok", "pending", "pending", "merge"])
            self.assertEqual(data["summary"]["pending_commits"], 2)


class TestMissingCloc(unittest.TestCase):
    def test_raises_before_touching_git(self):
        real = shutil.which
        shutil.which = lambda name: None
        try:
            with self.assertRaises(an.cl.ClocMissing):
                an.analyse("/definitely/not/a/repo", "/dev/null")
        finally:
            shutil.which = real
