"""The dashboard suite tests the page against tests/dashboard/fixture.py, so
the fixture must carry every key the analyser writes; otherwise the suite
passes against a page shape the tool no longer produces."""

import importlib.util
import os
import unittest

from clocwork import analyse as an

_spec = importlib.util.spec_from_file_location(
    "dashboard_fixture", os.path.join(os.path.dirname(__file__), "dashboard", "fixture.py"))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)

ENTRY = {"turns": 1, "models": {"claude-opus-5": {"input": 0, "output": 1, "cache_read": 0, "cache_write": 0}}}


class TestFixtureShape(unittest.TestCase):
    def test_the_tokens_block_has_the_analysers_keys(self):
        want = set(an.token_summary({}, []))
        for tokens in (True, False):
            with self.subTest(tokens=tokens):
                self.assertEqual(set(fixture.build(tokens=tokens)["summary"]["tokens"]), want)

    def test_a_source_entry_has_the_analysers_keys(self):
        want = set(an.token_summary({"2026-01-01": {"claude-code": ENTRY}}, [])["sources"][0])
        self.assertEqual(set(fixture.build()["summary"]["tokens"]["sources"][0]), want)


if __name__ == "__main__":
    unittest.main()
