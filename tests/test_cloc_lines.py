import json
import unittest

import cloc_lines as cl

EXT_TEXT = """swift           Swift
md              Markdown
m               MATLAB/Mathematica/Objective-C/MUMPS/Mercury
h               C/C++ Header
sh              Bourne Shell
"""


class TestPathRule(unittest.TestCase):
    def test_directory_named_tests(self):
        self.assertTrue(cl.is_test_path("MyApp/Tests/MyAppTests/A.swift"))
        self.assertTrue(cl.is_test_path("OldApp/Tests/B.swift"))

    def test_directory_suffixed_tests(self):
        self.assertTrue(cl.is_test_path("WinterUITests/Launch.swift"))
        self.assertTrue(cl.is_test_path("WinterTests/WinterTests.swift"))

    def test_non_test_directories(self):
        self.assertFalse(cl.is_test_path("MyApp/Testing/UX Test Plan.md"))
        self.assertFalse(cl.is_test_path("TestFlight/WhatToTest.en-US.txt"))
        self.assertFalse(cl.is_test_path("MyApp/App/Main.swift"))

    def test_filename_alone_does_not_count(self):
        self.assertFalse(cl.is_test_path("Tests.swift"))
        self.assertFalse(cl.is_test_path("App/FooTests.swift"))


class TestExtensionTable(unittest.TestCase):
    def setUp(self):
        self.table = cl.parse_extension_table(EXT_TEXT)

    def test_parses_rows(self):
        self.assertEqual(self.table["swift"], "Swift")
        self.assertEqual(self.table["sh"], "Bourne Shell")

    def test_language_with_slash_is_kept_whole(self):
        self.assertEqual(cl.language_for("Sources/x.h", self.table), "C/C++ Header")

    def test_lookup_is_case_insensitive_on_extension(self):
        self.assertEqual(cl.language_for("A/B.SWIFT", self.table), "Swift")

    def test_unknown_or_missing_extension_is_other(self):
        self.assertEqual(cl.language_for("Makefile", self.table), cl.OTHER)
        self.assertEqual(cl.language_for("a/b.unknownext", self.table), cl.OTHER)
        self.assertEqual(cl.language_for(".gitignore", self.table), cl.OTHER)


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


class TestParseDiff(unittest.TestCase):
    def setUp(self):
        self.table = cl.parse_extension_table(EXT_TEXT)

    def test_sums_added_and_removed_per_language(self):
        lines, tests = cl.parse_diff_json(DIFF_JSON, self.table)
        self.assertEqual(lines["Swift"], [5, 1, 3, 0, 1, 0])
        self.assertEqual(lines["Markdown"], [2, 0, 0, 0, 1, 0])

    def test_test_files_are_summed_separately(self):
        _, tests = cl.parse_diff_json(DIFF_JSON, self.table)
        self.assertEqual(tests, {"Swift": [2, 0, 1, 0, 0, 0]})

    def test_zero_rows_and_modified_are_ignored(self):
        lines, _ = cl.parse_diff_json(DIFF_JSON, self.table)
        self.assertNotIn(cl.OTHER, lines)          # pbxproj had all zeros
        self.assertEqual(lines["Swift"][2], 3)     # modified comment lines not added

    def test_empty_output(self):
        self.assertEqual(cl.parse_diff_json({}, self.table), ({}, {}))


class TestParseSnapshots(unittest.TestCase):
    def test_by_language(self):
        snap = cl.parse_snapshot_by_language(SNAPSHOT_LANG_JSON)
        self.assertEqual(snap, {"Swift": {"code": 5, "comment": 3, "blank": 1},
                                "Markdown": {"code": 2, "comment": 0, "blank": 1}})

    def test_by_file_splits_tests(self):
        table = cl.parse_extension_table(EXT_TEXT)
        all_files, tests = cl.parse_snapshot_by_file(SNAPSHOT_FILE_JSON, table)
        self.assertEqual(all_files["Swift"], {"code": 5, "comment": 3, "blank": 1})
        self.assertEqual(all_files["Markdown"], {"code": 2, "comment": 0, "blank": 1})
        self.assertEqual(tests, {"Swift": {"code": 2, "comment": 1, "blank": 0}})


import os
import shutil
import tempfile

from tests import repo_fixture as fx

HAVE_CLOC = shutil.which("cloc") is not None


class TestCache(unittest.TestCase):
    def test_roundtrip_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cache.json")
            c = cl.Cache(p)
            self.assertIsNone(c.get("abc"))
            c.put("abc", {"Swift": [1, 0, 0, 0, 0, 0]}, {})
            self.assertEqual(c.dirty, 1)
            c.save()
            self.assertEqual(c.dirty, 0)
            self.assertFalse(os.path.exists(p + ".tmp"))
            again = cl.Cache(p)
            self.assertEqual(again.get("abc"), {"lines": {"Swift": [1, 0, 0, 0, 0, 0]}, "test_lines": {}})

    def test_version_mismatch_starts_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cache.json")
            with open(p, "w") as f:
                json.dump({"version": 0, "commits": {"x": {"lines": {}, "test_lines": {}}}}, f)
            self.assertIsNone(cl.Cache(p).get("x"))


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

    def differ(self, repo, parent, commit, table):
        self.calls.append((parent, commit))
        if commit == "b" and getattr(self, "fail_b", False):
            raise cl.ClocError("boom")
        return ({"Swift": [1, 0, 0, 0, 0, 0]}, {})

    def test_cap_leaves_pending_and_skips_merges(self):
        res = cl.measure_commits("/nowhere", self.COMMITS, self.cache, {}, max_commits=2,
                                 differ=self.differ, log=lambda *a: None)
        self.assertEqual([c for _, c in self.calls], ["a", "b"])
        self.assertEqual(self.calls[0][0], cl.EMPTY_TREE)      # root diffed against the empty tree
        self.assertEqual(sorted(res.measured), ["a", "b"])
        self.assertEqual(res.pending, ["c"])
        self.assertEqual(res.failed, [])

    def test_second_run_uses_cache(self):
        cl.measure_commits("/nowhere", self.COMMITS, self.cache, {}, differ=self.differ, log=lambda *a: None)
        self.calls.clear()
        res = cl.measure_commits("/nowhere", self.COMMITS, self.cache, {}, differ=self.differ, log=lambda *a: None)
        self.assertEqual(self.calls, [])
        self.assertEqual(sorted(res.measured), ["a", "b", "c"])

    def test_failure_is_reported_and_not_cached(self):
        self.fail_b = True
        res = cl.measure_commits("/nowhere", self.COMMITS, self.cache, {}, differ=self.differ, log=lambda *a: None)
        self.assertEqual(res.failed, ["b"])
        self.assertIsNone(self.cache.get("b"))
        self.assertIn("a", res.measured)


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
        lines, tests = cl.diff_commit(self.tmp.name, None, self.hashes[0], self.table)
        self.assertEqual(lines, {"Swift": fx.SWIFT_ROW_1, "Markdown": fx.MARKDOWN_ROW_1})
        self.assertEqual(tests, {})

    def test_diff_with_test_file(self):
        lines, tests = cl.diff_commit(self.tmp.name, self.hashes[0], self.hashes[1], self.table)
        self.assertEqual(lines, {"Swift": fx.SWIFT_ROW_2})
        self.assertEqual(tests, {"Swift": fx.SWIFT_TEST_ROW_2})

    def test_snapshot(self):
        by_lang, all_files, tests = cl.snapshot(self.tmp.name, "HEAD", self.table)
        self.assertEqual(by_lang, {"Swift": fx.HEAD_SWIFT, "Markdown": fx.HEAD_MARKDOWN})
        self.assertEqual(all_files, by_lang)
        self.assertEqual(tests, {"Swift": fx.HEAD_TEST_SWIFT})

    def test_require_cloc_passes(self):
        cl.require_cloc()


if __name__ == "__main__":
    unittest.main()
