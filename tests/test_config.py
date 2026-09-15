import os
import tempfile
import unittest

from clocwork import config as cfg


class TestParse(unittest.TestCase):
    def test_defaults_when_empty(self):
        c = cfg.parse("", "x.toml")
        self.assertIsNone(c.title)
        self.assertTrue(c.rules.is_test("Tests/A.swift"))
        self.assertIsNone(c.agents.detect("Co-Authored-By: Jules <j>"))

    def test_full_file(self):
        c = cfg.parse('title = "MyApp"\n[tests]\ninclude = ["integration/**"]\nexclude = ["tests/fixtures/**"]\n'
                      '[agents]\nextra = [{ match = "Jules", name = "Jules" }]\n', "x.toml")
        self.assertEqual(c.title, "MyApp")
        self.assertTrue(c.rules.is_test("integration/a.go"))
        self.assertFalse(c.rules.is_test("tests/fixtures/a.json"))
        self.assertEqual(c.agents.detect("Co-Authored-By: Jules <j>"), "Jules")

    def test_replace(self):
        c = cfg.parse('[tests]\ninclude = ["qa/**"]\nreplace = true\n', "x.toml")
        self.assertFalse(c.rules.is_test("Tests/A.swift"))

    def test_invalid_toml_names_file_and_line(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.parse('title = "a"\n[tests\n', "/w/clocwork.toml")
        self.assertIn("/w/clocwork.toml", str(ctx.exception))
        self.assertIn("line 2", str(ctx.exception))

    def test_wrong_types_are_errors(self):
        with self.assertRaises(cfg.ConfigError):
            cfg.parse('[tests]\ninclude = "not-a-list"\n', "x.toml")
        with self.assertRaises(cfg.ConfigError):
            cfg.parse('[agents]\nextra = ["Jules"]\n', "x.toml")
        with self.assertRaises(cfg.ConfigError):
            cfg.parse('title = 3\n', "x.toml")


class TestLoad(unittest.TestCase):
    def test_absent_everywhere_is_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg.load(None, os.path.join(d, "ws"), os.path.join(d, "repo"))
            self.assertIsNone(c.source)
            self.assertIsNone(c.title)

    def test_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            ws, repo = os.path.join(d, "ws"), os.path.join(d, "repo")
            os.makedirs(ws)
            os.makedirs(repo)
            with open(os.path.join(repo, ".clocwork.toml"), "w") as f:
                f.write('title = "repo"\n')
            self.assertEqual(cfg.load(None, ws, repo).title, "repo")
            with open(os.path.join(ws, "clocwork.toml"), "w") as f:
                f.write('title = "ws"\n')
            self.assertEqual(cfg.load(None, ws, repo).title, "ws")
            explicit = os.path.join(d, "mine.toml")
            with open(explicit, "w") as f:
                f.write('title = "explicit"\n')
            self.assertEqual(cfg.load(explicit, ws, repo).title, "explicit")
            self.assertEqual(cfg.load(explicit, ws, repo).source, explicit)

    def test_explicit_missing_is_an_error(self):
        with self.assertRaises(cfg.ConfigError):
            cfg.load("/no/such/file.toml", None, None)


if __name__ == "__main__":
    unittest.main()
