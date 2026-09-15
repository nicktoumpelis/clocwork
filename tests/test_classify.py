import unittest

from clocwork import classify as cf


class TestBuiltinRules(unittest.TestCase):
    CASES = [
        # (path, is_test, note)
        ("Tests/AppTests.swift", True, "Xcode Tests directory"),
        ("WinterUITests/Flow.swift", True, "directory suffixed Tests"),
        ("App/Testsuite/x.swift", False, "Testsuite is not Tests"),
        ("App/main.swift", False, "plain source"),
        ("pkg/server_test.go", True, "Go filename"),
        ("pkg/server.go", False, "Go source"),
        ("tests/test_cli.py", True, "Python tests dir"),
        ("src/test_helpers.py", True, "Python test_ prefix"),
        ("src/helpers_test.py", True, "Python _test suffix"),
        ("conftest.py", True, "pytest conftest"),
        ("src/testing.py", False, "testing is not a test"),
        ("src/app.test.ts", True, "JS .test."),
        ("src/app.spec.jsx", True, "JS .spec."),
        ("src/__tests__/app.js", True, "__tests__ directory"),
        ("src/app.ts", False, "TS source"),
        ("spec/models/user_spec.rb", True, "Ruby spec dir and suffix"),
        ("lib/user_spec.rb", True, "Ruby suffix alone"),
        ("src/test/java/com/x/FooTest.java", True, "Maven layout"),
        ("src/main/java/com/x/FooTest.java", True, "JVM filename suffix"),
        ("src/main/java/com/x/Foo.java", False, "JVM source"),
        ("src/androidTest/java/x/A.kt", True, "Gradle androidTest"),
        ("Foo/Bar.cs", False, ".NET source"),
        ("Foo/BarTests.cs", True, ".NET filename suffix"),
        ("testdata/fixture.json", True, "Go testdata"),
        ("lib/thing_test.dart", True, "Dart"),
        ("test/thing_test.exs", True, "Elixir"),
        ("TESTS/x.py", True, "lowercase word forms are case-insensitive"),
        ("AppTESTS/x.swift", False, "capitalised suffix form is case-sensitive"),
        ("App/Contest.swift", False, "Contest is not a test"),
        ("MyApp/Testing/UX Test Plan.md", False, "Testing is not a test directory"),
        ("TestFlight/WhatToTest.en-US.txt", False, "TestFlight is not a test directory"),
        ("a.test.py", False, ".test. only counts for JS and TS"),
    ]

    def test_table(self):
        for path, want, note in self.CASES:
            with self.subTest(path=path, note=note):
                self.assertEqual(cf.DEFAULT_RULES.is_test(path), want)

    def test_backslashes_are_separators(self):
        self.assertTrue(cf.DEFAULT_RULES.is_test("Tests\\AppTests.swift"))


class TestConfiguredRules(unittest.TestCase):
    def test_include_adds_to_builtins(self):
        r = cf.TestRules(include=["integration/**", "e2e/*.py"])
        self.assertTrue(r.is_test("integration/deep/flow.go"))
        self.assertTrue(r.is_test("e2e/run.py"))
        self.assertTrue(r.is_test("Tests/A.swift"))

    def test_exclude_wins_over_everything(self):
        r = cf.TestRules(include=["integration/**"], exclude=["tests/fixtures/**", "integration/keep/**"])
        self.assertFalse(r.is_test("tests/fixtures/big.json"))
        self.assertFalse(r.is_test("integration/keep/x.go"))
        self.assertTrue(r.is_test("integration/other/x.go"))

    def test_replace_drops_builtins(self):
        r = cf.TestRules(include=["qa/**"], replace=True)
        self.assertFalse(r.is_test("Tests/A.swift"))
        self.assertFalse(r.is_test("pkg/a_test.go"))
        self.assertTrue(r.is_test("qa/a.go"))

    def test_double_star_matches_any_depth_and_star_stays_in_segment(self):
        r = cf.TestRules(include=["a/**/z.py", "b/*.py"], replace=True)
        self.assertTrue(r.is_test("a/z.py"))
        self.assertTrue(r.is_test("a/x/y/z.py"))
        self.assertTrue(r.is_test("b/q.py"))
        self.assertFalse(r.is_test("b/c/q.py"))


class TestExtensionTable(unittest.TestCase):
    TEXT = "swift   Swift\nh       C/C++ Header\nm       MATLAB/Mathematica/Objective-C/MUMPS/Mercury\n"

    def test_parses_rows(self):
        self.assertEqual(cf.parse_extension_table(self.TEXT)["swift"], "Swift")

    def test_language_with_slash_is_kept_whole(self):
        self.assertEqual(cf.parse_extension_table(self.TEXT)["h"], "C/C++ Header")

    def test_lookup_is_case_insensitive_on_extension(self):
        self.assertEqual(cf.language_for("A/B.SWIFT", {"swift": "Swift"}), "Swift")

    def test_unknown_or_missing_extension_is_other(self):
        self.assertEqual(cf.language_for("Makefile", {}), cf.OTHER)
        self.assertEqual(cf.language_for(".gitignore", {"gitignore": "X"}), cf.OTHER)
        self.assertEqual(cf.language_for("a.zzz", {}), cf.OTHER)


if __name__ == "__main__":
    unittest.main()
