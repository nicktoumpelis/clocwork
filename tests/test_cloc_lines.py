import json
import unittest

from clocwork import classify as cf
from clocwork import cloc as cl

EXT_TEXT = """swift           Swift
md              Markdown
m               MATLAB/Mathematica/Objective-C/MUMPS/Mercury
h               C/C++ Header
sh              Bourne Shell
"""


DIFF_JSON = {
    "header": {"cloc_version": "2.10"},
    "added": {
        "App/Main.swift": {"blank": 1, "comment": 2, "code": 3, "nFiles": 0},
        "Tests/AppTests.swift": {"blank": 0, "comment": 1, "code": 2, "nFiles": 0},
        "README.md": {"blank": 1, "comment": 0, "code": 2, "nFiles": 0},
        "project.pbxproj": {"blank": 0, "comment": 0, "code": 0, "nFiles": 0},
    },
    "removed": {
        "App/Main.swift": {"blank": 0, "comment": 0, "code": 1, "nFiles": 0},
        "Tests/AppTests.swift": {"blank": 0, "comment": 0, "code": 0, "nFiles": 0},
        "README.md": {"blank": 0, "comment": 0, "code": 0, "nFiles": 0},
    },
    "modified": {"App/Main.swift": {"blank": 0, "comment": 4, "code": 0, "nFiles": 0}},
    "same": {},
    "SUM": {"added": {"code": 7}},
}

SNAPSHOT_LANG_JSON = {
    "header": {},
    "Swift": {"nFiles": 2, "blank": 1, "comment": 3, "code": 5},
    "Markdown": {"nFiles": 1, "blank": 1, "comment": 0, "code": 2},
    "SUM": {"blank": 2, "comment": 3, "code": 7, "nFiles": 3},
}

SNAPSHOT_FILE_JSON = {
    "header": {},
    "App/Main.swift": {"blank": 1, "comment": 2, "code": 3, "language": "Swift"},
    "Tests/AppTests.swift": {"blank": 0, "comment": 1, "code": 2, "language": "Swift"},
    "README.md": {"blank": 1, "comment": 0, "code": 2, "language": "Markdown"},
    "SUM": {"blank": 2, "comment": 3, "code": 7, "nFiles": 3},
}


class TestDiffRows(unittest.TestCase):
    def test_keeps_added_and_removed_files_only(self):
        rows = cl.diff_rows(DIFF_JSON)
        self.assertEqual(set(rows), {"added", "removed"})
        self.assertEqual(rows["added"]["App/Main.swift"], {"code": 3, "comment": 2, "blank": 1})
        self.assertEqual(rows["removed"]["App/Main.swift"], {"code": 1, "comment": 0, "blank": 0})
        self.assertNotIn("header", rows["added"])
        self.assertNotIn("SUM", rows["added"])
        self.assertNotIn("nFiles", rows["added"]["App/Main.swift"])

    def test_empty(self):
        self.assertEqual(cl.diff_rows({}), {"added": {}, "removed": {}})


class TestClassifyRows(unittest.TestCase):
    def setUp(self):
        self.table = cf.parse_extension_table(EXT_TEXT)
        self.rows = cl.diff_rows(DIFF_JSON)

    def test_sums_added_and_removed_per_language(self):
        lines, tests = cl.classify_rows(self.rows, self.table, cf.DEFAULT_RULES)
        self.assertEqual(lines["Swift"], [5, 1, 3, 0, 1, 0])
        self.assertEqual(lines["Markdown"], [2, 0, 0, 0, 1, 0])

    def test_test_files_are_summed_separately(self):
        _, tests = cl.classify_rows(self.rows, self.table, cf.DEFAULT_RULES)
        self.assertEqual(tests, {"Swift": [2, 0, 1, 0, 0, 0]})

    def test_zero_rows_and_modified_are_ignored(self):
        lines, _ = cl.classify_rows(self.rows, self.table, cf.DEFAULT_RULES)
        self.assertNotIn(cf.OTHER, lines)          # pbxproj had all zeros
        self.assertEqual(lines["Swift"][2], 3)     # modified comment lines not added

    def test_reclassification_without_remeasuring(self):
        # Same rows, changed rules, changed result: the point of caching per file.
        _, before = cl.classify_rows(self.rows, self.table, cf.DEFAULT_RULES)
        _, after = cl.classify_rows(self.rows, self.table, cf.TestRules(include=["App/**"]))
        self.assertEqual(before, {"Swift": [2, 0, 1, 0, 0, 0]})
        self.assertEqual(after, {"Swift": [5, 1, 3, 0, 1, 0]})

    def test_changed_language_table_reclassifies_too(self):
        lines, _ = cl.classify_rows(self.rows, {"swift": "Swift", "md": "Text"}, cf.DEFAULT_RULES)
        self.assertEqual(lines["Text"], [2, 0, 0, 0, 1, 0])

    def test_empty(self):
        self.assertEqual(cl.classify_rows(cl.diff_rows({}), self.table, cf.DEFAULT_RULES), ({}, {}))


class TestParseSnapshots(unittest.TestCase):
    def test_by_language(self):
        snap = cl.parse_snapshot_by_language(SNAPSHOT_LANG_JSON)
        self.assertEqual(snap, {"Swift": {"code": 5, "comment": 3, "blank": 1},
                                "Markdown": {"code": 2, "comment": 0, "blank": 1}})

    def test_by_file_splits_tests(self):
        table = cf.parse_extension_table(EXT_TEXT)
        all_files, tests = cl.parse_snapshot_by_file(SNAPSHOT_FILE_JSON, table)
        self.assertEqual(all_files["Swift"], {"code": 5, "comment": 3, "blank": 1})
        self.assertEqual(all_files["Markdown"], {"code": 2, "comment": 0, "blank": 1})
        self.assertEqual(tests, {"Swift": {"code": 2, "comment": 1, "blank": 0}})


import concurrent.futures
import os
import shutil
import tempfile
import threading
import time
from unittest import mock

from tests import repo_fixture as fx

HAVE_CLOC = shutil.which("cloc") is not None


class TestCache(unittest.TestCase):
    ROWS = {"added": {"a.swift": {"code": 1, "comment": 0, "blank": 0}}, "removed": {}}

    def test_roundtrip_and_atomic_write_creating_the_directory(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "key", "cache.json")      # ~/.cache/clocwork/<key>/ does not exist yet
            c = cl.Cache(p)
            self.assertIsNone(c.get("abc"))
            c.put("abc", self.ROWS)
            self.assertEqual(c.dirty, 1)
            c.save()
            self.assertEqual(c.dirty, 0)
            self.assertFalse(os.path.exists(p + ".tmp"))
            with open(p) as f:
                self.assertEqual(json.load(f)["version"], 3)
            self.assertEqual(cl.Cache(p).get("abc"), self.ROWS)

    def test_version_2_is_discarded(self):
        # Per-language aggregates cannot be turned back into per-file rows.
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cache.json")
            with open(p, "w") as f:
                json.dump({"version": 2, "commits": {"x": {"lines": {"Swift": [1, 0, 0, 0, 0, 0]}, "test_lines": {}}}}, f)
            self.assertIsNone(cl.Cache(p).get("x"))

    def test_corrupt_cache_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cache.json")
            with open(p, "w") as f:
                f.write("{not valid json at all")
            self.assertIsNone(cl.Cache(p).get("x"))


class TestMatrixOrder(unittest.TestCase):
    TABLE = {"swift": "Swift", "md": "Markdown"}

    def test_languages_are_sorted_whatever_order_cloc_listed_the_files(self):
        # cloc's by-file output follows Perl hash order and differs between two
        # runs over the same commit; the matrices must not, or the workspace
        # file churns on every run and two runs cannot be compared byte for byte.
        counts = {"code": 1, "comment": 0, "blank": 0}
        forward = {"added": {"z.swift": counts, "a.md": counts}, "removed": {}}
        backward = {"added": {"a.md": counts, "z.swift": counts}, "removed": {}}
        for rows in (forward, backward):
            lines, _ = cl.classify_rows(rows, self.TABLE, cf.DEFAULT_RULES)
            self.assertEqual(list(lines), ["Markdown", "Swift"])


class TestMeasureCommits(unittest.TestCase):
    COMMITS = [
        {"hash": "a", "parent": None, "is_merge": False},
        {"hash": "b", "parent": "a", "is_merge": False},
        {"hash": "m", "parent": "b", "is_merge": True},
        {"hash": "c", "parent": "m", "is_merge": False},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = cl.Cache(os.path.join(self.tmp.name, "cache.json"))
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    TABLE = {"swift": "Swift"}

    def differ(self, repo, parent, commit):
        self.calls.append((parent, commit))
        if commit == "b" and getattr(self, "fail_b", False):
            raise cl.ClocError("boom")
        return {"added": {"a.swift": {"code": 1, "comment": 0, "blank": 0}}, "removed": {}}

    def measure(self, **kw):
        return cl.measure_commits("/nowhere", self.COMMITS, self.cache, self.TABLE, cf.DEFAULT_RULES,
                                  differ=self.differ, log=lambda *a: None, **kw)

    def test_cap_leaves_pending_and_skips_merges(self):
        res = self.measure(max_commits=2)
        self.assertEqual([c for _, c in self.calls], ["a", "b"])
        self.assertEqual(self.calls[0][0], cl.EMPTY_TREE)      # root diffed against the empty tree
        self.assertEqual(sorted(res.measured), ["a", "b"])
        self.assertEqual(res.measured["a"], ({"Swift": [1, 0, 0, 0, 0, 0]}, {}))   # classified, not raw rows
        self.assertEqual(res.pending, ["c"])
        self.assertEqual(res.failed, [])

    def test_second_run_uses_cache(self):
        self.measure()
        self.calls.clear()
        res = self.measure()
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(res.measured), ["a", "b", "c"])
        self.assertEqual(res.measured["c"], ({"Swift": [1, 0, 0, 0, 0, 0]}, {}))

    def test_cached_rows_are_reclassified_with_the_rules_of_this_run(self):
        self.measure()
        self.calls.clear()
        res = cl.measure_commits("/nowhere", self.COMMITS, self.cache, self.TABLE, cf.TestRules(include=["*.swift"]),
                                 differ=self.differ, log=lambda *a: None)
        self.assertEqual(self.calls, [])
        self.assertEqual(res.measured["a"][1], {"Swift": [1, 0, 0, 0, 0, 0]})

    def test_failure_is_reported_and_not_cached(self):
        self.fail_b = True
        res = self.measure()
        self.assertEqual(res.failed, ["b"])
        self.assertIsNone(self.cache.get("b"))
        self.assertIn("a", res.measured)

    def test_jobs_run_differs_at_the_same_time(self):
        # The first two calls meet at a two-party barrier, which only opens
        # when both are in flight at once. Under a single worker the second
        # party never arrives, the wait times out, and the test fails.
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        arrivals = []

        def differ(repo, parent, commit):
            with lock:
                arrivals.append(commit)
                k = len(arrivals)
            if k <= 2:
                barrier.wait()
            return self.differ(repo, parent, commit)

        res = cl.measure_commits("/nowhere", self.COMMITS, self.cache, self.TABLE, cf.DEFAULT_RULES,
                                 differ=differ, log=lambda *a: None, jobs=2)
        self.assertEqual(sorted(res.measured), ["a", "b", "c"])
        self.assertFalse(barrier.broken)

    def test_parallel_run_matches_the_serial_run(self):
        commits = self.COMMITS + [{"hash": "d", "parent": "c", "is_merge": False}]

        def differ(repo, parent, commit):
            if commit == "a":
                time.sleep(0.05)          # so a later failure ("d") completes first
            if commit in ("a", "d"):
                raise cl.ClocError("boom")
            return self.differ(repo, parent, commit)

        def measure(cache, jobs):
            return cl.measure_commits("/nowhere", commits, cache, self.TABLE, cf.DEFAULT_RULES,
                                      differ=differ, log=lambda *a: None, jobs=jobs)

        serial_cache = cl.Cache(os.path.join(self.tmp.name, "serial.json"))
        serial = measure(serial_cache, 1)
        parallel_cache = cl.Cache(os.path.join(self.tmp.name, "parallel.json"))
        parallel = measure(parallel_cache, 4)
        self.assertEqual(serial.failed, ["a", "d"])       # history order, not completion order
        self.assertEqual(parallel, serial)
        self.assertEqual(parallel_cache.entries, serial_cache.entries)

    def test_interrupt_saves_what_was_measured_and_cancels_the_queue(self):
        commits = [{"hash": f"c{i:02d}", "parent": None, "is_merge": False} for i in range(50)]
        called = []

        def differ(repo, parent, commit):
            called.append(commit)
            if commit == "c01":
                time.sleep(0.05)          # so c00's result is consumed before this one lands
                raise KeyboardInterrupt
            time.sleep(0.001)             # let the main thread in to cancel what is still queued
            return {"added": {"a.swift": {"code": 1, "comment": 0, "blank": 0}}, "removed": {}}

        with self.assertRaises(KeyboardInterrupt):
            cl.measure_commits("/nowhere", commits, self.cache, self.TABLE, cf.DEFAULT_RULES,
                               differ=differ, log=lambda *a: None, jobs=1)
        self.assertNotIn("c49", called)                                  # the queue was cancelled
        self.assertIsNotNone(cl.Cache(self.cache.path).get("c00"))       # the flush happened on the way out

    def test_jobs_still_running_at_an_interrupt_are_kept(self):
        commits = [{"hash": "slow", "parent": None, "is_merge": False},
                   {"hash": "boom", "parent": None, "is_merge": False}]

        def differ(repo, parent, commit):
            if commit == "boom":
                raise KeyboardInterrupt
            time.sleep(0.1)               # in flight when the interrupt lands; finishes during the join
            return {"added": {"a.swift": {"code": 1, "comment": 0, "blank": 0}}, "removed": {}}

        with self.assertRaises(KeyboardInterrupt):
            cl.measure_commits("/nowhere", commits, self.cache, self.TABLE, cf.DEFAULT_RULES,
                               differ=differ, log=lambda *a: None, jobs=2)
        self.assertIsNotNone(cl.Cache(self.cache.path).get("slow"))      # not thrown away, not re-measured next run

    def test_a_job_failing_during_the_shutdown_is_not_reported(self):
        # On a terminal Ctrl-C the in-flight cloc processes die with the run.
        # Their failures are noise while the user is aborting, and the next
        # run retries them, so the shutdown keeps results and says nothing.
        commits = [{"hash": "dying", "parent": None, "is_merge": False},
                   {"hash": "boom", "parent": None, "is_merge": False}]
        lines = []

        def differ(repo, parent, commit):
            if commit == "boom":
                raise KeyboardInterrupt
            time.sleep(0.1)
            raise cl.ClocError("cloc exited with -2")

        with self.assertRaises(KeyboardInterrupt):
            cl.measure_commits("/nowhere", commits, self.cache, self.TABLE, cf.DEFAULT_RULES,
                               differ=differ, log=lines.append, jobs=2)
        self.assertEqual([line for line in lines if "failed" in line], [])

    def test_a_second_interrupt_during_the_join_keeps_what_was_recorded(self):
        # The join waits for in-flight cloc runs; a second Ctrl-C there ends
        # the finally block early, so the save has to come before the join.
        commits = [{"hash": "c00", "parent": None, "is_merge": False},
                   {"hash": "boom", "parent": None, "is_merge": False}]

        def differ(repo, parent, commit):
            if commit == "boom":
                time.sleep(0.05)          # so c00 is recorded before this lands
                raise KeyboardInterrupt
            return {"added": {"a.swift": {"code": 1, "comment": 0, "blank": 0}}, "removed": {}}

        original = concurrent.futures.ThreadPoolExecutor.shutdown

        def interrupted_shutdown(pool, *args, **kwargs):
            original(pool, *args, **kwargs)
            raise KeyboardInterrupt       # the second Ctrl-C, landing while the pool joins its workers

        concurrent.futures.ThreadPoolExecutor.shutdown = interrupted_shutdown
        try:
            with self.assertRaises(KeyboardInterrupt):
                cl.measure_commits("/nowhere", commits, self.cache, self.TABLE, cf.DEFAULT_RULES,
                                   differ=differ, log=lambda *a: None, jobs=1)
        finally:
            concurrent.futures.ThreadPoolExecutor.shutdown = original
        self.assertIsNotNone(cl.Cache(self.cache.path).get("c00"))


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestRealCloc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)
        cls.table = cl.load_extension_table()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_diff_root_commit(self):
        lines, tests = cl.classify_rows(cl.diff_commit(self.tmp.name, None, self.hashes[0]), self.table, cf.DEFAULT_RULES)
        self.assertEqual(lines, {"Swift": fx.SWIFT_ROW_1, "Markdown": fx.MARKDOWN_ROW_1})
        self.assertEqual(tests, {})

    def test_diff_with_test_file(self):
        lines, tests = cl.classify_rows(cl.diff_commit(self.tmp.name, self.hashes[0], self.hashes[1]), self.table, cf.DEFAULT_RULES)
        self.assertEqual(lines, {"Swift": fx.SWIFT_ROW_2})
        self.assertEqual(tests, {"Swift": fx.SWIFT_TEST_ROW_2})

    def test_snapshot(self):
        by_lang, all_files, tests = cl.snapshot(self.tmp.name, "HEAD", self.table)
        self.assertEqual(by_lang, {"Swift": fx.HEAD_SWIFT, "Markdown": fx.HEAD_MARKDOWN})
        self.assertEqual(all_files, by_lang)
        self.assertEqual(tests, {"Swift": fx.HEAD_TEST_SWIFT})

    def test_require_cloc_passes(self):
        cl.require_cloc()


class TestRequireCloc(unittest.TestCase):
    """require_cloc against stand-in `cloc` scripts, each alone on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path_with_cloc(self, script):
        # A directory per script: the version lookup is memoised by path.
        d = tempfile.mkdtemp(dir=self.tmp.name)
        with open(os.path.join(d, "cloc"), "w") as f:
            f.write("#!/bin/sh\n" + script + "\n")
        os.chmod(os.path.join(d, "cloc"), 0o755)
        return mock.patch.dict(os.environ, {"PATH": d})

    def test_a_missing_cloc_is_refused(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp.name}):
            with self.assertRaisesRegex(cl.ClocMissing, "not installed or not on PATH"):
                cl.require_cloc()

    def test_a_cloc_older_than_2_06_is_refused(self):
        for version in ("1.64", "1.98", "2.04", "2.05"):
            with self.subTest(version=version), self.path_with_cloc(f"echo {version}"):
                with self.assertRaises(cl.ClocMissing) as caught:
                    cl.require_cloc()
                self.assertIn(f"cloc {version} ", str(caught.exception))
                self.assertIn("2.06 or later", str(caught.exception))

    def test_cloc_2_06_and_later_is_accepted(self):
        # 10.00 sorts before 2.06 as a string; the comparison must be numeric.
        for version in ("2.06", "2.07", "2.10", "3.00", "10.00"):
            with self.subTest(version=version), self.path_with_cloc(f"echo {version}"):
                cl.require_cloc()

    def test_a_version_cloc_does_not_print_plainly_is_not_held_against_it(self):
        # A build that prints something else is let through; a cloc that
        # fails outright is reported by the first real run instead.
        for script in ("echo 'cloc development build'", "exit 2"):
            with self.subTest(script=script), self.path_with_cloc(script):
                cl.require_cloc()


BY_FILE_CSV = '''language,filename,blank,comment,code,"github.com/AlDanial/cloc v 2.10  T=0.5 s"
Swift,App/Main.swift,1,2,3
XML,MyApp/MyApp.xcprivacy,0,0,12
XML,MyApp.xcodeproj/xcshareddata/xcschemes/MyApp.xcscheme,0,0,80
Markdown,README.md,1,0,2
SUM,,2,2,97
'''


class TestLearnedExtensions(unittest.TestCase):
    def test_parse_by_file_csv_maps_extension_to_language(self):
        learned = cl.parse_by_file_csv(BY_FILE_CSV)
        self.assertEqual(learned, {"swift": "Swift", "xcprivacy": "XML", "xcscheme": "XML", "md": "Markdown"})

    def test_overlay_wins_over_show_ext(self):
        base = cf.parse_extension_table("swift  Swift\nm  MATLAB/Mathematica/Objective-C/MUMPS/Mercury\n")
        merged = cl.merge_language_tables(base, {"m": "Objective-C", "xcprivacy": "XML"})
        self.assertEqual(merged["m"], "Objective-C")
        self.assertEqual(merged["xcprivacy"], "XML")
        self.assertEqual(merged["swift"], "Swift")
        self.assertEqual(base["m"], "MATLAB/Mathematica/Objective-C/MUMPS/Mercury")   # input not mutated


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestBuildLanguageTable(unittest.TestCase):
    def test_learns_from_head(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            table = cl.build_language_table(d, "HEAD")
            self.assertEqual(table["swift"], "Swift")
            self.assertEqual(table["md"], "Markdown")
            self.assertIn("py", table)   # base show-ext entries are still present


if __name__ == "__main__":
    unittest.main()
