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

    def test_parts_are_packed_whole_into_lines(self):
        parts = ["Copilot from 2025-02-01", "Cursor from 2025-02-02", "Claude Opus 4.6 from 2025-02-03"]
        self.assertEqual(ui.pack(parts, " · ", 50),
                         ["Copilot from 2025-02-01 · Cursor from 2025-02-02", "Claude Opus 4.6 from 2025-02-03"])
        self.assertEqual(ui.pack(parts, " · ", 200), [" · ".join(parts)])
        self.assertEqual(ui.pack(["x" * 30], " · ", 10), ["x" * 30])     # a part wider than the line stands alone
        self.assertEqual(ui.pack("one string", " · ", 5), ["one string"])
        self.assertEqual(ui.pack([], " · ", 5), [""])

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
        self.assertEqual((commits.value, ui.joined(commits.rest, " · ")),
                         ("3,800", "2,910 AI-assisted (77%) · 880 human · 10 misc"))
        self.assertEqual(commits.plain, "Commits: 3,800 (2,910 AI-assisted, 880 human, 10 misc)")
        self.assertEqual((tokens.value, ui.joined(tokens.rest, " · ")),
                         ("1.2B", "lifetime · 1.0M measured over 61 days · 41 AI commits carry none"))
        self.assertEqual(tokens.plain.splitlines(), [
            "Tokens: 1,203,456,789 lifetime (1,000,000 measured over 61 days, 1,202,456,789 estimated at 9,577 per AI line)",
            "41 AI commits carry no token figure (Copilot CLI, Cursor): no token logs from their agent cover their work"])
        self.assertEqual((tests.value, ui.joined(tests.rest, " · ")), ("38.4%", "48,213 of 125,560 code lines at main"))
        self.assertEqual(tests.plain, "Test code at main: 48,213 of 125,560 code lines (38.4%)")
        # In history order, whatever the dict's order.
        self.assertEqual((agents.value, ui.joined(agents.rest, " · ")),
                         ("", "Cursor from 2025-02-02 · Claude Opus 4.6 from 2025-02-03"))
        self.assertEqual(agents.plain, "First appearances: Cursor 2025-02-02 (e69d979), Claude Opus 4.6 2025-02-03 (fc11f30)")

    def test_no_tokens_no_code_and_no_agents(self):
        summary = dict(SUMMARY, total_commits=0, ai_assisted_commits=0, human_only_commits=0, misc_commits=0,
                       head_snapshot={"all": {}, "tests": {}},
                       tokens=dict(SUMMARY["tokens"], measured_total=0))
        rows = ui.summary_rows(summary, {}, "docs")
        self.assertEqual([r.label for r in rows], ["Commits", "Tokens", "Tests"])
        self.assertEqual(rows[0].rest, ["0 AI-assisted", "0 human", "0 misc"])
        self.assertEqual(rows[1].plain, "Tokens: none (no agent token archive for this repository)")
        self.assertEqual(rows[2].plain, "Test code at docs: none")


import io


class Stream(io.StringIO):
    def __init__(self, tty=False, encoding="utf-8"):
        super().__init__()
        self._tty, self._encoding = tty, encoding

    def isatty(self):
        return self._tty

    @property
    def encoding(self):
        return self._encoding


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def a_run(report, clock):
    """A three-phase run with a warning, a detail and progress."""
    report.header("poly", "/tmp/poly-stats")
    with report.phase("Tokens", 1, 3):
        report.detail("scanned", "4 days of Codex CLI logs")
        report.done(["Codex CLI 4 days"], "Archive now 4 days, 10 tokens (+4 days, +10 tokens)")
        clock.now += 0.2
    with report.phase("History", 2, 3):
        report.status("measuring 100 new commits with cloc")
        started = clock.now
        for n in range(1, 101):
            clock.now += 0.05
            report.progress(n, 100, clock.now - started)
        report.warn("3 commits could not be measured by cloc")
        report.done(["4 commits on main @ 7801b0b"], "97 measured, 0 from cache")
    with report.phase("Dashboard", 3, 3):
        report.done(["index.html", "115 KB"])
    report.summary(ui.summary_rows(SUMMARY, FIRSTS, "main"))
    report.table("Lines at main", ("", "code"), [("Swift", "98,120")])
    report.finish("/tmp/poly-stats/index.html")


class TestPlain(unittest.TestCase):
    def run_plain(self, verbose=False):
        out, clock = Stream(), Clock()
        a_run(ui.Plain(out, verbose, clock=clock), clock)
        return out.getvalue()

    def test_default_lines(self):
        lines = self.run_plain().splitlines()
        self.assertEqual(lines[:4], ["clocwork " + ui.__version__ + ": poly -> /tmp/poly-stats",
                                     "[1/3] Tokens: Codex CLI 4 days (0.2s)",
                                     "  Archive now 4 days, 10 tokens (+4 days, +10 tokens)",
                                     "[2/3] History: measuring 100 new commits with cloc"])
        self.assertIn("[2/3] History: measured 50/100, 2.5s elapsed, ~2.5s left", lines)
        self.assertNotIn("[2/3] History: measured 100/100, 5.0s elapsed, ~0.0s left", lines)
        self.assertIn("WARNING: 3 commits could not be measured by cloc", lines)
        self.assertIn("[3/3] Dashboard: index.html, 115 KB (0.0s)", lines)
        self.assertIn("Test code at main: 48,213 of 125,560 code lines (38.4%)", lines)
        self.assertEqual(lines[-1], "Open: /tmp/poly-stats/index.html")
        self.assertFalse(any(l.startswith("  scanned") or l.startswith("Lines at") for l in lines))

    def test_verbose_adds_details_under_a_phase_line_and_the_table(self):
        lines = self.run_plain(verbose=True).splitlines()
        at = lines.index("[1/3] Tokens")
        self.assertEqual(lines[at + 1], "  scanned: 4 days of Codex CLI logs")
        self.assertIn("Lines at main:", lines)
        self.assertIn("  Swift  98,120", lines)

    def test_plain_output_has_no_escape_codes_redraws_or_non_ascii(self):
        for verbose in (False, True):
            text = self.run_plain(verbose)
            self.assertNotIn("\x1b", text)
            self.assertNotIn("\r", text)
            text.encode("ascii")

    def test_a_phase_that_raises_says_so_and_re_raises(self):
        out = Stream()
        report = ui.Plain(out, clock=Clock())
        with self.assertRaises(KeyboardInterrupt):
            with report.phase("History", 2, 3):
                raise KeyboardInterrupt
        self.assertEqual(out.getvalue(), "[2/3] History: stopped after 0.0s\n")


class TestTerminal(unittest.TestCase):
    def run_terminal(self, verbose=False, unicode=True, width=80):
        out, clock = Stream(tty=True), Clock()
        a_run(ui.Terminal(out, verbose, unicode=unicode, width=width, clock=clock), clock)
        return out.getvalue()

    def test_phases_redraw_in_place_and_end_with_a_newline(self):
        text = self.run_terminal()
        self.assertIn("\r\x1b[2K", text)
        finished = [l for l in text.split("\n") if "✓" in l]
        self.assertEqual(len(finished), 3)
        for line in finished:
            self.assertNotIn("\r", line.split("\r\x1b[2K")[-1])

    def test_redraws_are_throttled(self):
        text = self.run_terminal()
        # 100 progress calls 0.05s apart: at most one redraw per 0.1s, plus the last.
        self.assertLessEqual(text.count("/100"), 52)
        self.assertIn("100/100", text)

    def test_warnings_follow_their_phase_line(self):
        visible = [l.split("\r\x1b[2K")[-1] for l in self.run_terminal().split("\n")]
        history = next(i for i, l in enumerate(visible) if "History" in l and "✓" in l)
        self.assertIn("97 measured, 0 from cache", visible[history + 1])
        self.assertIn("⚠", visible[history + 2])
        self.assertIn("3 commits could not be measured", visible[history + 2])

    def test_details_and_the_table_only_with_verbose(self):
        self.assertNotIn("4 days of Codex CLI logs", self.run_terminal())
        self.assertNotIn("Lines at main", self.run_terminal())
        verbose = self.run_terminal(verbose=True)
        self.assertIn("4 days of Codex CLI logs", verbose)
        self.assertIn("Lines at main", verbose)

    def test_ascii_glyphs_when_the_stream_is_not_utf8(self):
        text = self.run_terminal(unicode=False)
        text.encode("ascii")
        self.assertIn("+", text)

    def test_the_summary_and_the_path_close_the_run(self):
        text = self.run_terminal()
        self.assertIn("38.4%", text)
        self.assertTrue(text.rstrip("\n").endswith("/tmp/poly-stats/index.html"), text[-80:])

    def test_a_phase_that_raises_ends_its_line_with_a_cross(self):
        out = Stream(tty=True)
        report = ui.Terminal(out, clock=Clock())
        with self.assertRaises(ValueError):
            with report.phase("History", 2, 3):
                raise ValueError("boom")
        self.assertIn("✗", out.getvalue())
        self.assertTrue(out.getvalue().endswith("\n"))

    def test_a_long_path_wraps_only_at_spaces(self):
        out = Stream(tty=True)
        report = ui.Terminal(out, verbose=True, width=40, clock=Clock())
        report.detail("saved", "/tmp/a-very-long-directory-name/poly-stats/full_commit_data.json")
        self.assertIn("/tmp/a-very-long-directory-name/poly-stats/full_commit_data.json", out.getvalue())

    def test_a_live_line_never_exceeds_the_width(self):
        out, clock = Stream(tty=True), Clock()
        report = ui.Terminal(out, width=40, clock=clock)
        with report.phase("History", 2, 3):
            report.status("x" * 200)
            live = out.getvalue().split("\r\x1b[2K")[-1]
            self.assertLess(len(live), 40)


class TestQuietAndChoose(unittest.TestCase):
    def test_quiet_prints_nothing(self):
        out, clock = Stream(), Clock()
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            a_run(ui.Reporter(), clock)
        self.assertEqual(out.getvalue(), "")

    def test_choose(self):
        tty, pipe = Stream(tty=True), Stream()
        cases = [((True, False, tty, {}), ui.Reporter),
                 ((False, False, tty, {}), ui.Terminal),
                 ((False, True, tty, {"NO_COLOR": ""}), ui.Terminal),   # empty: not set, per no-color.org
                 ((False, False, tty, {"NO_COLOR": "1"}), ui.Plain),
                 ((False, False, tty, {"TERM": "dumb"}), ui.Plain),
                 ((False, False, pipe, {}), ui.Plain)]
        for args, kind in cases:
            with self.subTest(args=args[:2] + (args[3],)):
                self.assertIs(type(ui.choose(*args)), kind)
        self.assertTrue(ui.choose(False, True, tty, {}).verbose)
        self.assertFalse(ui.choose(False, False, Stream(tty=True, encoding="cp1252"), {}).unicode)
        self.assertTrue(ui.choose(False, False, tty, {}).unicode)

    def test_errors_reach_stderr_at_every_level(self):
        from contextlib import redirect_stderr
        for report in (ui.Reporter(), ui.Plain(Stream()), ui.Terminal(Stream(tty=True))):
            err = io.StringIO()
            with redirect_stderr(err):
                report.error("no such repository")
            self.assertEqual(err.getvalue(), "clocwork: no such repository\n")
