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


if __name__ == "__main__":
    unittest.main()
