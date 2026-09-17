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

    # Antigravity writes no trailer of its own, so these are the ones people
    # add by hand, as found in public commits on 2026-09-17 with
    # `gh search commits "Co-authored-by: Antigravity"`.
    ANTIGRAVITY_TRAILERS = (
        "Antigravity AI <antigravity-ai@users.noreply.github.com>",
        "Antigravity (3.1 Pro) <gemini@google.com>",
        "DeepMind Antigravity <antigravity@google.com>",
        "Google Antigravity <242056456+google-antigravity@users.noreply.github.com>",
        "Antigravity <326255689+antigravity-selvakk2k[bot]@users.noreply.github.com>",
        "AGY <noreply@antigravity.dev>",   # only the address says which agent it was
        "Antigravity CLI (Gemini 3.8 Flash) <antigravity@stevens-imac-3>",
    )

    def test_antigravity_trailers(self):
        for text in self.ANTIGRAVITY_TRAILERS:
            with self.subTest(text=text):
                self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: " + text), "Antigravity")

    def test_antigravity_comes_before_the_gemini_row(self):
        # Antigravity names the Gemini model it ran, so the Gemini row claims
        # the trailer if it is reached first, and a plain Gemini trailer must
        # still reach it.
        both = "Fix\n\nCo-Authored-By: Antigravity CLI (Gemini 3.8 Flash) <antigravity@stevens-imac-3>"
        self.assertEqual(ag.detect_agent(both), "Antigravity")
        self.assertEqual(ag.detect_agent(TRAILER.format("Gemini CLI")), "Gemini")
        self.assertEqual(ag.detect_agent(TRAILER.format("Google Gemini")), "Gemini")

    def test_one_commit_crediting_three_agents_keeps_its_first_trailer(self):
        # A shape seen in public commits: three trailers, one per agent. The
        # body's order decides, as it did before Antigravity was a row.
        body = ("Fix\n\n"
                "Co-authored-by: Google Gemini <gemini-ai@users.noreply.github.com>\n"
                "Co-authored-by: Antigravity AI <antigravity-ai@users.noreply.github.com>\n"
                "Co-authored-by: Anthropic Claude <claude-ai@users.noreply.github.com>")
        self.assertEqual(ag.detect_agent(body), "Gemini")

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
