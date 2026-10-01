import os
import tempfile
import unittest

from clocwork import analyse as an
from clocwork import blame as bl
from tests import repo_fixture as fx

PORCELAIN = """\
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1 1 2
author T
summary Initial
filename f
\tline one
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 2 2
\tline two
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 1 3 1
author T
summary Later
previous aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa f
filename f
\taaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 9 9 looks like a header but is content
"""


class TestPorcelain(unittest.TestCase):
    def test_counts_one_line_per_header(self):
        self.assertEqual(bl.parse_porcelain(PORCELAIN),
                         {"a" * 40: 2, "b" * 40: 1})


class TestPullRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)
        cls.extra = fx.add_branch_merge(cls.tmp.name)
        cls.commits = an.parse_log(cls.tmp.name, "main")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_number_from_subject(self):
        self.assertEqual(an.pr_number("Merge pull request #12 from me/branch"), 12)
        self.assertEqual(an.pr_number("Add the parser (#34)"), 34)
        self.assertEqual(an.pr_number('Revert "Add the parser (#34)" (#40)"'[:-1]), 40)
        self.assertIsNone(an.pr_number("Fix (#34) in the middle"))
        self.assertIsNone(an.pr_number("Merge branch 'feature' into main"))

    def test_members_are_what_each_merge_brought_in(self):
        members = an.pr_members(self.commits)
        initial, tests, notes, merge = self.hashes
        extra, merge2 = self.extra
        self.assertEqual(members, {merge: [notes], merge2: [extra]})

    def test_a_linear_history_has_no_members(self):
        self.assertEqual(an.pr_members(self.commits[:2]), {})
        self.assertEqual(an.pr_members([]), {})

    def test_rows_take_the_pull_request_of_their_merge(self):
        results = [{"full_hash": c["hash"], "message": c["message"]} for c in self.commits]
        an.assign_prs(self.commits, results)
        initial, tests, notes, merge = self.hashes
        by_hash = {r["full_hash"]: r["pr"] for r in results}
        self.assertEqual(by_hash[merge], 1)
        self.assertEqual(by_hash[notes], 1)
        self.assertIsNone(by_hash[initial])
        self.assertIsNone(by_hash[tests])
        # A branch merge without a pull request number gives its members none.
        extra, merge2 = self.extra
        self.assertIsNone(by_hash[merge2])
        self.assertIsNone(by_hash[extra])

    def test_a_member_keeps_its_own_squash_number(self):
        initial, tests, notes, merge = self.hashes
        results = [{"full_hash": c["hash"], "message": c["message"]} for c in self.commits]
        results[2]["message"] = "Notes (#7)"
        an.assign_prs(self.commits, results)
        self.assertEqual({r["full_hash"]: r["pr"] for r in results}[notes], 7)


class TestLinesAt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)
        cls.commits = an.parse_log(cls.tmp.name, "main")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def results(self):
        return [{"full_hash": c["hash"], "agent": c["agent"]} for c in self.commits]

    def test_every_line_of_every_file_is_credited_once(self):
        files = ["App/main.swift", "README.md", "Tests/AppTests.swift", "Notes.md", "Gone.md"]
        cache = bl.Cache(os.path.join(self.tmp.name, "blame_cache.json"))
        totals, fresh = bl.lines_at(self.tmp.name, "main", files, cache, jobs=2)
        def lines(f):
            with open(os.path.join(self.tmp.name, f)) as fh:
                return len(fh.read().splitlines())
        expected = sum(lines(f) for f in files[:4])
        self.assertEqual(sum(totals.values()), expected)
        self.assertEqual(fresh, 4)       # Gone.md is not at main, so it is skipped, not blamed
        initial, tests, notes, merge = self.hashes
        self.assertEqual(set(totals), {initial, tests, notes})
        self.assertEqual(totals[notes], len(fx.NOTES.splitlines()))

    def test_second_run_reads_the_cache(self):
        path = os.path.join(self.tmp.name, "blame_cache2.json")
        files = ["README.md", "Notes.md"]
        first, fresh = bl.lines_at(self.tmp.name, "main", files, bl.Cache(path), jobs=1)
        self.assertEqual(fresh, 2)
        again, fresh = bl.lines_at(self.tmp.name, "main", files, bl.Cache(path), jobs=1)
        self.assertEqual((again, fresh), (first, 0))

    def test_by_agent_credits_the_commit_author(self):
        initial, tests, notes, merge = self.hashes
        totals = {initial: 10, tests: 4, notes: 3, "f" * 40: 2}
        self.assertEqual(bl.by_agent(totals, self.results()),
                         {"total": 19, "human": 13, "by_agent": {"Claude Opus 4.6": 4}, "unattributed": 2})

    def test_an_unknown_path_is_an_error_not_a_crash_elsewhere(self):
        with self.assertRaises(bl.BlameError):
            bl.tree(self.tmp.name, "no-such-ref")


if __name__ == "__main__":
    unittest.main()
