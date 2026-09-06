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


if __name__ == "__main__":
    unittest.main()
