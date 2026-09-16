import unittest

from clocwork import agents as ag

TRAILER = "Fix\n\nCo-Authored-By: {} <noreply@example.com>"


class TestClaude(unittest.TestCase):
    def test_family_first_and_version_first(self):
        self.assertEqual(ag.detect_agent(TRAILER.format("Claude Opus 4.6")), "Claude Opus 4.6")
        self.assertEqual(ag.detect_agent(TRAILER.format("Claude 3.5 Sonnet")), "Claude Sonnet 3.5")

    def test_context_suffix(self):
        self.assertEqual(ag.detect_agent(TRAILER.format("Claude Opus 5 (1M context)")), "Claude Opus 5 (1M)")

    def test_greedy_version(self):
        self.assertEqual(ag.detect_agent(TRAILER.format("Claude Fable 5.1")), "Claude Fable 5.1")

    def test_unknown_claude(self):
        self.assertEqual(ag.detect_agent(TRAILER.format("Claude")), ag.UNKNOWN_CLAUDE)

    def test_first_trailer_wins(self):
        body = "x\n\nCo-Authored-By: Claude Opus 4.6 <a>\nCo-Authored-By: Claude Sonnet 4.5 <b>"
        self.assertEqual(ag.detect_agent(body), "Claude Opus 4.6")


class TestVendors(unittest.TestCase):
    def test_each_vendor(self):
        for text, name in (("GitHub Copilot", "Copilot"), ("Cursor Agent", "Cursor"), ("Codex", "Codex"),
                           ("Devin AI", "Devin"), ("aider (gpt-4o)", "aider"), ("Gemini CLI", "Gemini"),
                           ("gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>",
                            "Gemini Code Assist")):
            with self.subTest(text=text):
                self.assertEqual(ag.detect_agent(TRAILER.format(text)), name)

    def test_mention_outside_a_trailer_is_not_attributed(self):
        self.assertIsNone(ag.detect_agent("Tidy up after Copilot suggested this\n\nSigned-off-by: A <a@b>"))
        self.assertIsNone(ag.detect_agent("See CLAUDE.md and the claude-fix branch"))

    def test_unrecognised_trailer_is_unmatched(self):
        self.assertIsNone(ag.detect_agent(TRAILER.format("Jane Doe")))

    def test_extra_from_config(self):
        table = ag.AgentTable(extra=[{"match": "Jules", "name": "Jules"}])
        self.assertEqual(table.detect(TRAILER.format("Jules by Google")), "Jules")
        self.assertIsNone(ag.DEFAULT_AGENTS.detect(TRAILER.format("Jules by Google")))

    def test_empty_body(self):
        self.assertIsNone(ag.detect_agent(""))
        self.assertIsNone(ag.detect_agent(None))


if __name__ == "__main__":
    unittest.main()
