import time
import unittest

from clocwork import agents as ag

TRAILER = "Fix\n\nCo-Authored-By: {} <noreply@example.com>"
# Spelled out in the table below, so a row can also say "no agent at all".
UNKNOWN = ag.UNKNOWN_CLAUDE


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

    def test_a_claude_model_in_the_trailer_wins_over_the_vendor(self):
        # Antigravity runs Claude models too, and names the model it ran. A
        # Claude model is parsed before any vendor row is reached, so no row
        # order can change these - the same as Cursor's trailers always have.
        self.assertEqual(ag.detect_agent(TRAILER.format("Antigravity (Claude Sonnet 4.5)")),
                         "Claude Sonnet 4.5")
        self.assertEqual(ag.detect_agent(TRAILER.format("Cursor (Claude Sonnet 4.5)")),
                         "Claude Sonnet 4.5")

    def test_one_commit_crediting_three_agents_keeps_its_first_trailer(self):
        # The shape one public repository writes: three trailers on every
        # commit, in this order. Its Claude trailer names no model, so these
        # commits were credited to an unknown Claude version before
        # Antigravity was a row and still are - the body's order decides.
        body = ("Fix\n\n"
                "Co-authored-by: Anthropic Claude <claude-ai@users.noreply.github.com>\n"
                "Co-authored-by: Antigravity AI <antigravity-ai@users.noreply.github.com>\n"
                "Co-authored-by: Google Gemini <gemini-ai@users.noreply.github.com>")
        self.assertEqual(ag.detect_agent(body), ag.UNKNOWN_CLAUDE)
        # Written the other way round, the same trailers credit Antigravity,
        # which is what makes this a test of the order rather than of Claude.
        claude, antigravity, gemini = body.splitlines()[2:]
        reordered = "Fix\n\n" + "\n".join([antigravity, gemini, claude])
        self.assertEqual(ag.detect_agent(reordered), "Antigravity")

    # Every trailer form this repository has recorded from a public commit,
    # across the Antigravity and OpenCode searches and the earlier vendors.
    # The matching rule may get stricter, but not at the cost of one of these.
    RECORDED = (
        ("GitHub Copilot <x@y>", "Copilot"),
        ("Cursor Agent <x@y>", "Cursor"),
        ("Codex <noreply@openai.com>", "Codex"),
        ("Devin AI <x@y>", "Devin"),
        ("aider (gpt-4o) <x@y>", "aider"),
        ("Gemini CLI <x@y>", "Gemini"),
        ("Google Gemini <gemini-ai@users.noreply.github.com>", "Gemini"),
        ("gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>",
         "Gemini Code Assist"),
        ("Antigravity AI <antigravity-ai@users.noreply.github.com>", "Antigravity"),
        ("Antigravity (3.1 Pro) <gemini@google.com>", "Antigravity"),
        ("DeepMind Antigravity <antigravity@google.com>", "Antigravity"),
        ("Google Antigravity <242056456+google-antigravity@users.noreply.github.com>", "Antigravity"),
        ("Antigravity <326255689+antigravity-selvakk2k[bot]@users.noreply.github.com>", "Antigravity"),
        ("AGY <noreply@antigravity.dev>", "Antigravity"),
        ("Antigravity CLI (Gemini 3.8 Flash) <antigravity@stevens-imac-3>", "Antigravity"),
        ("Antigravity Agent <antigravity-bot@google.internal>", "Antigravity"),
        ("Antigravity AI <ai@antigravity.google>", "Antigravity"),
        ("opencode <noreply@opencode.ai>", "OpenCode"),
        ("GLM-5.3 via OpenCode <noreply@opencode.ai>", "OpenCode"),
        ("DeepSeek V4.1 Flash as OpenCode <noreply@opencode.ai>", "OpenCode"),
        ("opencode-go/mimo-v2.5 <noreply@opencode.ai>", "OpenCode"),
        ("opencode (glm-5.2) <ai@local>", "OpenCode"),
        ("opencode-agent[bot] <41898282+opencode-agent[bot]@users.noreply.github.com>",
         "OpenCode GitHub agent"),
        ("Anthropic Claude <claude-ai@users.noreply.github.com>", UNKNOWN),
        ("Cursor (Claude Sonnet 4.5) <x@y>", "Claude Sonnet 4.5"),
    )

    def test_every_recorded_trailer_form_still_names_its_agent(self):
        for text, name in self.RECORDED:
            with self.subTest(text=text):
                self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: " + text), name)

    def test_mention_outside_a_trailer_is_not_attributed(self):
        self.assertIsNone(ag.detect_agent("Tidy up after Copilot suggested this\n\nSigned-off-by: A <a@b>"))
        self.assertIsNone(ag.detect_agent("See CLAUDE.md and the claude-fix branch"))

    def test_a_vendor_word_inside_a_longer_word_is_not_that_vendor(self):
        # "Antigravity" is a common enough word to appear in a company's name
        # or its domain. A contributor at one is a person, not an agent, and
        # the module would rather miss an agent than credit the wrong one.
        for text in ("Jane Doe <jane@antigravity-drones.example>",
                     "Jane Doe <jane@mail.antigravity-drones.example>",
                     "Antigravitybot <bot@example.com>",
                     "Codexterous <hi@example.com>",
                     "Cursory Notes <hi@example.com>",
                     "A Coder <coder@opencoded.example>"):
            with self.subTest(text=text):
                self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: " + text))

    def test_a_digit_is_part_of_a_name_too(self):
        # A version glued to a name may be a product of its own, and this
        # module would rather miss an agent than name the wrong one. Spelled
        # the way real trailers do it, both still match.
        self.assertIsNone(ag.detect_agent(TRAILER.format("Codex5")))
        self.assertIsNone(ag.detect_agent(TRAILER.format("Antigravity2")))
        self.assertEqual(ag.detect_agent(TRAILER.format("Codex 5")), "Codex")
        self.assertEqual(ag.detect_agent(TRAILER.format("Antigravity-2")), "Antigravity")
        # On either side: a digit before the name joins it too.
        self.assertIsNone(ag.detect_agent(TRAILER.format("v2codex")))
        self.assertIsNone(ag.detect_agent(TRAILER.format("3gemini")))

    def test_a_trailer_written_without_brackets_is_read_as_an_address(self):
        # A bare address is the form a hand-written trailer most often takes,
        # and its domain must not fall under the looser rule for a name.
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: jane@antigravity-drones.example"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: bot@mail.antigravity-drones.example"))
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: jane@antigravity.dev"), "Antigravity")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: antigravity@google.com"), "Antigravity")
        # A local part that ends in punctuation after its letters is still one.
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: jane.@antigravity-drones"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: bot-@codex-labs"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Jane bot+@codex-labs"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: jane_@antigravity-drones"))
        # Whatever its local part is spelled with, it is still an address.
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: josé@antigravity-drones"))
        self.assertIsNone(ag.detect_agent('Fix\n\nCo-Authored-By: "j d"@antigravity-drones'))

    def test_a_note_beside_the_address_still_names_its_agent(self):
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Someone <s@x.example> (via Codex)"),
                         "Codex")

    def test_an_address_that_is_no_domain_is_read_as_a_name(self):
        # Without an `@` there is no domain to be strict about, so the word
        # rule applies. No recorded trailer takes this shape; the recorded
        # `antigravity@stevens-imac-3` has an `@`, and matches by its local
        # part - the test below it covers that.
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: bot <opencode-bot>"), "OpenCode")
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: bot <opencodebot>"))

    def test_whitespace_inside_an_address_does_not_hide_its_domain(self):
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Bot <x@ opencode.ai >"), "OpenCode")

    def test_only_the_trailers_own_address_is_an_address(self):
        # A second address is someone else's - a former one, a reviewer's -
        # and says nothing about who wrote the commit, whatever its domain.
        self.assertIsNone(ag.detect_agent(
            "Fix\n\nCo-Authored-By: Jane <jane@example.com> <bob@antigravity-drones.example>"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@example.com> (was jane@opencode.ai)"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@example.com> <bot@opencode.ai>"))
        # Spaced out inside its brackets, it is still one address.
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@example.com> <bot@ opencode.ai >"))

    def test_a_handle_is_a_name_not_an_address(self):
        # An address has someone's name before its `@`; "@codex" is a handle,
        # the way people write an agent's name, and it stays in the name.
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: @cursor <x@y.example>"), "Cursor")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane (@codex) <x@y.example>"), "Codex")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@x.example> (cc @codex)"), "Codex")
        # Punctuation before the `@` is how a handle is written, not a local
        # part, so these stay names beside the trailer's own address.
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@x.example> [@codex]"), "Codex")
        self.assertEqual(ag.detect_agent('Fix\n\nCo-Authored-By: Jane <jane@x.example> "@codex"'), "Codex")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@x.example> cc:@codex"), "Codex")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: [@codex]"), "Codex")
        # A local part has a letter or digit in it; "_@codex" and "-@codex"
        # have none, so they are handles too.
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@x.example> _@codex"), "Codex")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@x.example> -@codex"), "Codex")
        # And in a trailer without brackets, a handle before the address does
        # not take the address's place.
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Jane (@codex) jane@x.example"), "Codex")

    def test_a_domain_in_a_note_is_judged_as_a_domain(self):
        # Wherever a domain is written, the name of whoever owns it sits in
        # it, so it has to match label by label there too.
        self.assertIsNone(ag.detect_agent(
            "Fix\n\nCo-Authored-By: Jane Doe <jane@antigravity-drones.example>, antigravity-drones.example"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Jane <jane@example.com> (see antigravity-drones.example)"))
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: Someone <s@x.example> (via opencode.ai)"), "OpenCode")

    def test_a_version_is_not_a_domain(self):
        # A domain ends in a label of letters. Model ids end in digits or in
        # a suffix glued to them, so they stay words.
        self.assertEqual(ag.detect_agent(TRAILER.format("gemini-2.5-pro")), "Gemini")
        self.assertEqual(ag.detect_agent(TRAILER.format("Antigravity (gemini-2.5-pro)")), "Antigravity")
        self.assertEqual(ag.detect_agent(TRAILER.format("opencode/gemini-2.5-pro")), "OpenCode")
        self.assertEqual(ag.detect_agent(TRAILER.format("GPT-5.1-Codex")), "Codex")
        # Two digits after the dot are still a version, and a domain ends
        # where its label does, not partway into "mimo-v2".
        self.assertEqual(ag.detect_agent(TRAILER.format("gemini-1.15")), "Gemini")
        self.assertEqual(ag.detect_agent(TRAILER.format("opencode-go.mimo-v2")), "OpenCode")

    def test_a_note_after_a_bare_address_still_names_its_agent(self):
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: jane@x.example (via Codex)"), "Codex")
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: jane@antigravity-drones.example (reviewed)"))

    def test_a_vendor_word_in_the_address_counts_only_as_a_whole_label(self):
        # The domain is where a company's name sits, so a label has to match
        # outright; the local part is the agent's own, so a word in it counts.
        self.assertEqual(ag.detect_agent(TRAILER.format("AGY").replace(
            "noreply@example.com", "noreply@antigravity.dev")), "Antigravity")
        self.assertEqual(ag.detect_agent("Fix\n\nCo-Authored-By: AGY <antigravity-ai@example.com>"),
                         "Antigravity")
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: AGY <agy@antigravityresearch.example>"))
        # A label is whole on both sides.
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Bot <x@myopencode.ai>"))
        self.assertIsNone(ag.detect_agent("Fix\n\nCo-Authored-By: Bot <x@mail.my-opencode.ai>"))

    def test_unrecognised_trailer_is_unmatched(self):
        self.assertIsNone(ag.detect_agent(TRAILER.format("Jane Doe")))

    def test_extra_from_config(self):
        table = ag.AgentTable(extra=[{"match": "Jules", "name": "Jules"}])
        self.assertEqual(table.detect(TRAILER.format("Jules by Google")), "Jules")
        self.assertIsNone(ag.DEFAULT_AGENTS.detect(TRAILER.format("Jules by Google")))

    def test_a_built_in_row_wins_over_an_extra_that_overlaps_it(self):
        # Extras name what the built-ins do not, so a workspace cannot rename
        # a built-in agent. What bounds the short needle below is the word
        # rule, not this ordering.
        table = ag.AgentTable(extra=[{"match": "Antigravity IDE", "name": "Antigravity IDE"},
                                     {"match": "code", "name": "Some Editor"}])
        self.assertEqual(table.detect(TRAILER.format("Antigravity IDE")), "Antigravity")
        self.assertEqual(table.detect(TRAILER.format("opencode")), "OpenCode")
        # And the short needle claims nothing of its own: a needle has to be
        # a whole word in the name or local part, or a whole label of the
        # domain.
        self.assertIsNone(table.detect(TRAILER.format("opencoded")))

    def test_an_extra_matches_by_the_same_rule_as_a_built_in(self):
        table = ag.AgentTable(extra=[{"match": "Jules", "name": "Jules"}])
        self.assertEqual(table.detect(TRAILER.format("Jules (agent)")), "Jules")
        self.assertIsNone(table.detect(TRAILER.format("Julesy")))

    def test_a_dotted_extra_matches_whole_labels(self):
        # A needle with a dot in it is a domain's name, matched as a run of
        # whole labels wherever the trailer writes it.
        table = ag.AgentTable(extra=[{"match": "jules.google", "name": "Jules"}])
        self.assertEqual(table.detect("Co-Authored-By: Bot <x@jules.google>"), "Jules")
        self.assertEqual(table.detect("Co-Authored-By: Bot <x@mail.jules.google>"), "Jules")
        self.assertEqual(table.detect("Co-Authored-By: Jules.Google <x@example.com>"), "Jules")
        self.assertIsNone(table.detect("Co-Authored-By: Bot <x@jules.google-mirror.example>"))

    def test_a_long_trailer_takes_no_longer_than_its_length(self):
        # Each pattern is tried once per token, not once per character, so a
        # line of any length costs about its length. Quadratic, these took
        # seconds at 10,000 characters; the bound leaves a wide margin.
        for label, text in (("letters", "a" * 20000), ("quotes", '"' * 20000),
                            ("dotted labels", "a." * 10000 + "b"),
                            ("letters beside an address", "Jane <j@x.example> " + "a" * 20000)):
            with self.subTest(label=label):
                start = time.perf_counter()
                ag.detect_agent("Fix\n\nCo-Authored-By: " + text)
                self.assertLess(time.perf_counter() - start, 0.5)

    def test_empty_body(self):
        self.assertIsNone(ag.detect_agent(""))
        self.assertIsNone(ag.detect_agent(None))


if __name__ == "__main__":
    unittest.main()
