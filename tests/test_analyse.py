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
