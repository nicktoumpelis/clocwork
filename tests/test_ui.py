import unittest

from clocwork import ui


class TestFormatting(unittest.TestCase):
    def test_durations(self):
        for seconds, shown in ((0.2, "0.2s"), (59.9, "59.9s"), (59.96, "1m00s"), (242, "4m02s"),
                               (3780, "1h03m")):
            with self.subTest(seconds=seconds):
                self.assertEqual(ui.duration(seconds), shown)

    def test_sizes(self):
        self.assertEqual((ui.size(0), ui.size(117_760), ui.size(1_258_291)), ("0 KB", "115 KB", "1.2 MB"))

    def test_compact_counts(self):
        self.assertEqual([ui.compact(n) for n in (950, 12_345, 1_234_567, 1_203_456_789)],
                         ["950", "12.3K", "1.2M", "1.2B"])

    def test_paths_under_home_are_shortened(self):
        self.assertEqual(ui.short_path("/home/me/code/x", "/home/me"), "~/code/x")
        self.assertEqual(ui.short_path("/home/me", "/home/me"), "~")
        self.assertEqual(ui.short_path("/home/meadow/x", "/home/me"), "/home/meadow/x")
        self.assertEqual(ui.short_path("/tmp/x", "/home/me"), "/tmp/x")

    def test_parts_are_joined_and_a_string_is_kept(self):
        self.assertEqual((ui.joined(["a", "b"], " · "), ui.joined("a, b", " · ")), ("a · b", "a, b"))

    def test_bar_halves_fill_the_width(self):
        for fraction in (0, 0.25, 0.51, 0.99, 1, 1.5, -1):
            for unicode in (True, False):
                head, tail = ui.bar(fraction, 20, unicode)
                with self.subTest(fraction=fraction, unicode=unicode):
                    self.assertEqual(len(head) + len(tail), 20)
        self.assertEqual(ui.bar(0.5, 10, False), ("#####", "-----"))
        self.assertEqual(ui.bar(0.55, 10, True), ("━━━━━╸", "━━━━"))
        self.assertEqual(ui.bar(1, 4, False), ("####", ""))

    def test_columns_align_left_then_right(self):
        self.assertEqual(ui.columns(("", "code", "drift"), [("Swift", "98,120", "+0"), ("Go", "5", "-12")]),
                         ["         code  drift", "Swift  98,120     +0", "Go          5    -12"])


SUMMARY = {"total_commits": 3800, "ai_assisted_commits": 2910, "human_only_commits": 880, "misc_commits": 10,
           "head_snapshot": {"all": {"a.swift": {"code": 125_560}}, "tests": {"t.swift": {"code": 48_213}}},
           "tokens": {"measured_total": 1_000_000, "lifetime_total": 1_203_456_789, "measured_days": 61,
                      "estimated_total": 1_202_456_789, "ratio": 9_577, "unmeasured_agent_commits": 41,
                      "unmeasured_agents": ["Copilot CLI", "Cursor"]}}
FIRSTS = {"Cursor": {"date": "2025-02-02", "hash": "e69d979", "index": 1},
          "Claude Opus 4.6": {"date": "2025-02-03", "hash": "fc11f30", "index": 2}}


class TestSummaryRows(unittest.TestCase):
    def test_every_row_on_a_measured_history(self):
        rows = ui.summary_rows(SUMMARY, FIRSTS, "main")
        self.assertEqual([r.label for r in rows], ["Commits", "Tokens", "Tests", "Agents"])
        commits, tokens, tests, agents = rows
        self.assertEqual((commits.value, commits.rest),
                         ("3,800", "2,910 AI-assisted (77%) · 880 human · 10 misc"))
        self.assertEqual(commits.plain, "Commits: 3,800 (2,910 AI-assisted, 880 human, 10 misc)")
        self.assertEqual((tokens.value, tokens.rest),
                         ("1.2B", "lifetime · 1.0M measured over 61 days · 41 AI commits carry none"))
        self.assertEqual(tokens.plain.splitlines(), [
            "Tokens: 1,203,456,789 lifetime (1,000,000 measured over 61 days, 1,202,456,789 estimated at 9,577 per AI line)",
            "41 AI commits carry no token figure (Copilot CLI, Cursor): no token logs from their agent cover their work"])
        self.assertEqual((tests.value, tests.rest), ("38.4%", "48,213 of 125,560 code lines at main"))
        self.assertEqual(tests.plain, "Test code at main: 48,213 of 125,560 code lines (38.4%)")
        # In history order, whatever the dict's order.
        self.assertEqual((agents.value, agents.rest),
                         ("", "Cursor from 2025-02-02 · Claude Opus 4.6 from 2025-02-03"))
        self.assertEqual(agents.plain, "First appearances: Cursor 2025-02-02 (e69d979), Claude Opus 4.6 2025-02-03 (fc11f30)")

    def test_no_tokens_no_code_and_no_agents(self):
        summary = dict(SUMMARY, total_commits=0, ai_assisted_commits=0, human_only_commits=0, misc_commits=0,
                       head_snapshot={"all": {}, "tests": {}},
                       tokens=dict(SUMMARY["tokens"], measured_total=0))
        rows = ui.summary_rows(summary, {}, "docs")
        self.assertEqual([r.label for r in rows], ["Commits", "Tokens", "Tests"])
        self.assertEqual(rows[0].rest, "0 AI-assisted · 0 human · 0 misc")
        self.assertEqual(rows[1].plain, "Tokens: none (no agent token archive for this repository)")
        self.assertEqual(rows[2].plain, "Test code at docs: none")
