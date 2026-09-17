import json
import os
import re
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from clocwork import analyse as an
from clocwork import config as cfg
from clocwork import paths
from clocwork import sources as src
from tests import repo_fixture as fx

HAVE_CLOC = shutil.which("cloc") is not None


class TestParseLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_commits_in_history_order_with_parents(self):
        commits = an.parse_log(self.tmp.name, "main")
        self.assertEqual([c["hash"] for c in commits], self.hashes)
        self.assertEqual(commits[0]["parents"], [])
        self.assertEqual(commits[1]["parents"], [self.hashes[0]])
        self.assertEqual(commits[3]["parents"][0], self.hashes[1])   # merge's first parent is main
        self.assertEqual(len(commits[3]["parents"]), 2)

    def test_agent_and_message(self):
        commits = an.parse_log(self.tmp.name, "main")
        self.assertEqual(commits[1]["agent"], "Claude Opus 4.6")
        self.assertIsNone(commits[0]["agent"])
        self.assertEqual(commits[3]["message"], "Merge pull request #1 from x/feature")
        self.assertEqual(commits[0]["date"][:10], "2025-01-01")


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestAnalyse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hashes = fx.make_repo(cls.tmp.name)
        cls.out = os.path.join(cls.tmp.name, "out.json")
        cls.cache = os.path.join(cls.tmp.name, "cache.json")
        cls.archive = os.path.join(cls.tmp.name, "token_usage.json")
        cls.data = an.analyse(cls.tmp.name, cls.out, cls.cache, cls.archive, log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_languages_ordered_by_code_at_head(self):
        self.assertEqual(self.data["languages"], ["Swift", "Markdown"])

    def test_per_commit_matrices(self):
        c = self.data["commits"]
        self.assertEqual(c[0]["lines"], {"Swift": fx.SWIFT_ROW_1, "Markdown": fx.MARKDOWN_ROW_1})
        self.assertEqual(c[0]["test_lines"], {})
        self.assertEqual(c[1]["lines"], {"Swift": fx.SWIFT_ROW_2})
        self.assertEqual(c[1]["test_lines"], {"Swift": fx.SWIFT_TEST_ROW_2})
        self.assertEqual(c[2]["lines"], {"Markdown": fx.MARKDOWN_ROW_3})
        self.assertEqual(c[3]["lines"], {})
        self.assertEqual([x["status"] for x in c], ["ok", "ok", "ok", "merge"])
        self.assertEqual(c[3]["agent"], "Misc")
        self.assertNotIn("swift_delta", c[0])

    def test_snapshot_and_reconciliation(self):
        s = self.data["summary"]
        self.assertEqual(s["head_snapshot"]["all"], {"Swift": fx.HEAD_SWIFT, "Markdown": fx.HEAD_MARKDOWN})
        self.assertEqual(s["head_snapshot"]["tests"], {"Swift": fx.HEAD_TEST_SWIFT})
        self.assertEqual(s["running_totals"]["all"], s["head_snapshot"]["all"])
        zero = {"code": 0, "comment": 0, "blank": 0}
        self.assertEqual(s["reconciliation"], {"Swift": zero, "Markdown": zero})
        self.assertEqual(s["mapping_check"], {"Swift": zero, "Markdown": zero})
        self.assertEqual(s["unmeasured_commits"], 0)
        self.assertEqual(s["pending_commits"], 0)

    def test_counts_and_legacy_keys_removed(self):
        self.assertEqual(self.data["summary"]["misc_commits"], 1)
        self.assertEqual(self.data["summary"]["ai_assisted_commits"], 1)
        self.assertEqual(self.data["summary"]["human_only_commits"], 2)
        for key in ("daily", "biggest_gains", "biggest_drops", "agent_stats"):
            self.assertNotIn(key, self.data)
        self.assertEqual(self.data["first_appearances"]["Claude Opus 4.6"]["hash"], self.hashes[1][:7])
        with open(self.out) as f:
            self.assertEqual(json.load(f)["languages"], ["Swift", "Markdown"])

    def test_cache_is_written_and_reused(self):
        with open(self.cache) as f:
            cache = json.load(f)
        self.assertEqual(sorted(cache["commits"]), sorted(self.hashes[:3]))
        calls = []
        original = an.cl.diff_commit
        an.cl.diff_commit = lambda *a, **k: calls.append(a) or original(*a, **k)
        try:
            an.analyse(self.tmp.name, self.out, self.cache, self.archive, log=lambda *a: None)
        finally:
            an.cl.diff_commit = original
        self.assertEqual(calls, [])

    def test_cap_marks_pending(self):
        with tempfile.TemporaryDirectory() as d:
            hashes = fx.make_repo(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), max_commits=1, log=lambda *a: None)
            self.assertEqual([c["status"] for c in data["commits"]], ["ok", "pending", "pending", "merge"])
            self.assertEqual(data["summary"]["pending_commits"], 2)

    def test_jobs_reach_the_measuring_pass(self):
        seen = {}
        original = an.cl.measure_commits

        def spy(*a, **k):
            seen.update(k)
            return original(*a, **k)

        an.cl.measure_commits = spy
        try:
            an.analyse(self.tmp.name, self.out, self.cache, self.archive, jobs=3, log=lambda *a: None)
        finally:
            an.cl.measure_commits = original
        self.assertEqual(seen["jobs"], 3)

    def test_every_commit_carries_a_tokens_figure(self):
        # Zero when nothing is attributed, so the page can rely on the key.
        self.assertTrue(all(isinstance(c["tokens"], int) for c in self.data["commits"]))

    def test_every_commit_carries_a_token_kind(self):
        self.assertEqual({c["token_kind"] for c in self.data["commits"]}, {""})

    def test_commit_records_have_the_dashboard_fixtures_keys(self):
        from tests.test_fixture_shape import fixture
        self.assertEqual(set(fixture.build()["commits"][0]), set(self.data["commits"][0]))

    def test_summary_carries_a_tokens_block(self):
        t = self.data["summary"]["tokens"]
        self.assertEqual(t["measured_total"], 0)      # no transcripts for the fixture repo
        self.assertEqual(t["per_day"], [])
        self.assertEqual(t["sources"], [])
        # The fixture repository has one Claude commit and no logs on this machine.
        self.assertEqual((t["unmeasured_agent_commits"], t["unmeasured_agents"]), (1, ["Claude Code"]))


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestNonPrMerge(unittest.TestCase):
    def test_multi_parent_commit_is_a_merge(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            extra, merge = fx.add_branch_merge(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), log=lambda *a: None)
            by_hash = {c["full_hash"]: c for c in data["commits"]}
            self.assertEqual(by_hash[extra]["lines"], {"Markdown": [1, 0, 0, 0, 0, 0]})
            self.assertEqual(by_hash[merge]["status"], "merge")
            self.assertEqual(by_hash[merge]["agent"], "Misc")
            self.assertEqual(by_hash[merge]["lines"], {})
            zero = {"code": 0, "comment": 0, "blank": 0}
            self.assertEqual(data["summary"]["reconciliation"]["Markdown"], zero)   # no double counting
            self.assertEqual(data["summary"]["misc_commits"], 2)


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestInputs(unittest.TestCase):
    def test_not_a_repository(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(paths.NotARepository):
                an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), log=lambda *a: None)

    def test_empty_repository_is_an_error_not_an_empty_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            with self.assertRaises(an.NoCommits):
                an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), log=lambda *a: None)

    def test_configured_rules_change_the_test_split(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            conf = cfg.parse('[tests]\ninclude = ["App/**"]\n', "x")
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"),
                              config=conf, log=lambda *a: None)
            self.assertEqual(data["commits"][0]["test_lines"], {"Swift": fx.SWIFT_ROW_1})
            self.assertEqual(data["summary"]["head_snapshot"]["tests"]["Swift"], fx.HEAD_SWIFT)

    def test_extensionless_files_count_as_cloc_names_them_in_every_commit(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_extensionless_repo(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"),
                              log=lambda *a: None)
            self.assertEqual(data["commits"][0]["lines"],
                             {lang: [2, 0, 0, 0, 0, 0] for _, lang in fx.EXTENSIONLESS.values()})
            self.assertEqual(data["commits"][1]["lines"], {"Bourne Shell": [1, 0, 0, 0, 0, 0]})
            s = data["summary"]
            self.assertEqual(s["head_snapshot"]["all"]["Bourne Shell"], {"code": 3, "comment": 0, "blank": 0})
            zero = {"code": 0, "comment": 0, "blank": 0}
            self.assertEqual(set(s["mapping_check"]), {lang for _, lang in fx.EXTENSIONLESS.values()})
            self.assertEqual(s["mapping_check"], {lang: zero for lang in s["mapping_check"]})
            self.assertEqual(s["reconciliation"], {lang: zero for lang in s["mapping_check"]})

    def test_claude_code_tokens_land_only_on_claude_commits_and_the_rest_are_named(self):
        # The polyglot fixture credits Copilot, Cursor and Claude Opus 4.6 on
        # three days; the archive holds Claude Code's record for Claude's day.
        with tempfile.TemporaryDirectory() as d:
            fx.make_polyglot_repo(d)
            archive = os.path.join(d, "t.json")
            with open(archive, "w") as f:
                json.dump({"version": 2, "days": {"2025-02-03": {"claude-code": {"turns": 1, "models": {
                    "claude-opus-4-6": {"input": 0, "output": 70, "cache_read": 0, "cache_write": 0}}}}}}, f)
            lines = []
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), archive, log=lines.append)
            tokens = {c["agent"]: c["tokens"] for c in data["commits"] if c["agent"]}
            kinds = {c["agent"]: c["token_kind"] for c in data["commits"] if c["agent"]}
            self.assertEqual((kinds["Claude Opus 4.6"], kinds["Copilot"], kinds["Cursor"]), ("m", "", ""))
            self.assertEqual((tokens["Claude Opus 4.6"], tokens["Copilot"], tokens["Cursor"]), (70, 0, 0))
            self.assertIn("  2 AI commits carry no token figure (Copilot, Cursor): "
                          "no token logs from their agent cover their work", lines)

    def test_configured_agents_are_used(self):
        # The polyglot fixture's last commit credits "Jules", which no built-in
        # rule knows: unattributed by default, attributed once config names it.
        with tempfile.TemporaryDirectory() as d:
            fx.make_polyglot_repo(d)
            args = (d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"))
            plain = an.analyse(*args, log=lambda *a: None)
            self.assertIsNone(plain["commits"][3]["agent"])
            conf = cfg.parse('[agents]\nextra = [{ match = "Jules", name = "Jules" }]\n', "x")
            data = an.analyse(*args, config=conf, log=lambda *a: None)
            self.assertEqual(data["commits"][3]["agent"], "Jules")
            self.assertIn("Jules", data["first_appearances"])

    def test_branch_snapshot_and_test_share_follow_the_requested_ref(self):
        # A `docs` branch, not merged, adds a Python test file; main stays
        # checked out with an untracked docs/ directory of the same name, which
        # cloc would take for the ref if it were given the bare branch name.
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            fx._git(d, "checkout", "-q", "-b", "docs")
            fx._write(d, "tests/test_x.py", "def test_x():\n    assert True\n")
            fx._git(d, "add", ".")
            fx._git(d, "commit", "-q", "-m", "Python test", date="2025-01-07T10:00:00+00:00")
            fx._git(d, "checkout", "-q", "main")
            fx._write(d, "docs/decoy.md", "# decoy\n")
            fx._write(d, "main/decoy.md", "# decoy\n")
            args = (d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"))
            lines = []
            on_docs = an.analyse(*args, branch="docs", log=lines.append)
            self.assertEqual(on_docs["summary"]["total_commits"], 5)
            self.assertEqual(on_docs["summary"]["head_snapshot"]["tests"]["Python"]["code"], 2)
            self.assertEqual({l: v for l, v in on_docs["summary"]["reconciliation"].items() if any(v.values())}, {})
            self.assertTrue(any(l.startswith("  Test code at docs:") for l in lines), lines)
            on_main = an.analyse(*args, log=lambda *a: None)
            self.assertEqual(on_main["summary"]["total_commits"], 4)
            self.assertNotIn("Python", on_main["summary"]["head_snapshot"]["all"])
            self.assertEqual(on_main["summary"]["head_snapshot"]["all"]["Swift"], fx.HEAD_SWIFT)

    def test_shallow_clone_is_warned_about(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src")
            os.makedirs(src)
            fx.make_repo(src)
            shallow = os.path.join(d, "shallow")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + src, shallow], check=True, capture_output=True)
            lines = []
            an.analyse(shallow, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), log=lines.append)
            self.assertTrue(any("shallow" in l.lower() and "WARNING" in l for l in lines), lines)

    def test_explicit_branch(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"),
                              branch="feature", log=lambda *a: None)
            self.assertEqual(data["summary"]["total_commits"], 3)

    def test_run_summary_reports_the_test_share_at_head(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            lines = []
            an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), os.path.join(d, "t.json"), log=lines.append)
            share = [l for l in lines if "Test code at main" in l]
            self.assertEqual(len(share), 1)
            self.assertIn(f"{fx.HEAD_TEST_SWIFT['code']:,} of {fx.HEAD_SWIFT['code'] + fx.HEAD_MARKDOWN['code']:,}", share[0])


class TestMissingCloc(unittest.TestCase):
    def test_raises_before_touching_git(self):
        real = shutil.which
        shutil.which = lambda name: None
        try:
            with self.assertRaises(an.cl.ClocMissing):
                an.analyse("/definitely/not/a/repo", "/dev/null", "/dev/null", "/dev/null")
        finally:
            shutil.which = real


class TestTokenSummary(unittest.TestCase):
    """The estimator works on plain dicts, so it needs no git fixture."""

    def results(self):
        # Two AI days and one human day. Row layout is
        # [codeAdded, codeRemoved, commentAdded, commentRemoved, blankAdded, blankRemoved].
        return [
            {"date": "2026-01-24", "agent": "Claude Opus 4.5", "lines": {"Swift": [80, 20, 0, 0, 0, 0]}},
            {"date": "2026-08-06", "agent": "Claude Opus 5", "lines": {"Swift": [40, 10, 0, 0, 0, 0]}},
            {"date": "2024-10-01", "agent": None, "lines": {"Swift": [500, 0, 0, 0, 0, 0]}},
            {"date": "2026-08-06", "agent": an.MISC, "lines": {}},
        ]

    def archive(self):
        return {"2026-08-06": {"claude-code": {"turns": 3, "models": {"claude-opus-5": {
            "input": 0, "output": 500, "cache_read": 4500, "cache_write": 0}}}}}

    def test_ratio_is_measured_tokens_over_covered_ai_churn(self):
        t = an.token_summary(self.archive(), self.results())
        # 5,000 tokens over 50 AI-attributed lines on 2026-08-06.
        self.assertEqual(t["ratio"], 100.0)

    def test_archived_days_are_measured(self):
        t = an.token_summary(self.archive(), self.results())
        self.assertIn(["2026-08-06", 5000, "m"], t["per_day"])
        self.assertEqual(t["measured_total"], 5000)
        self.assertEqual(t["measured_days"], 1)

    def test_uncovered_ai_days_are_estimated_at_the_ratio(self):
        t = an.token_summary(self.archive(), self.results())
        # 100 lines of AI churn on 2026-01-24 at 100 tokens per line.
        self.assertIn(["2026-01-24", 10000, "e"], t["per_day"])
        self.assertEqual(t["estimated_total"], 10000)
        self.assertEqual(t["lifetime_total"], 15000)

    def test_human_only_days_are_absent_not_estimated(self):
        t = an.token_summary(self.archive(), self.results())
        self.assertEqual([r for r in t["per_day"] if r[0] == "2024-10-01"], [])

    def test_derived_shares_and_coverage(self):
        t = an.token_summary(self.archive(), self.results())
        self.assertAlmostEqual(t["cache_read_share"], 0.9)
        self.assertEqual(t["output_per_line"], 10)      # 500 output over 50 lines changed
        self.assertEqual(t["coverage_start"], "2026-08-06")

    def test_cost_follows_the_token_ceiling(self):
        t = an.token_summary(self.archive(), self.results())
        # Opus 5: 500 output at $25/MTok plus 4,500 cache reads at $0.50/MTok.
        self.assertAlmostEqual(t["cost_usd"], 0.0125 + 0.00225)
        # 5,000 measured tokens against a 15,000 lifetime ceiling: three times the cost.
        self.assertAlmostEqual(t["lifetime_cost_usd"], t["cost_usd"] * t["lifetime_total"] / t["measured_total"])
        self.assertEqual(t["unpriced_tokens"], 0)

    def test_an_empty_archive_yields_zeroes_not_a_crash(self):
        t = an.token_summary({}, self.results())
        self.assertEqual(t["ratio"], 0.0)
        self.assertEqual(t["lifetime_total"], 0)
        self.assertEqual(t["per_day"], [])
        self.assertIsNone(t["coverage_start"])
        self.assertEqual(t["energy_kwh"], 0.0)
        self.assertEqual(t["co2_kg"], 0.0)


class TestEnergyEstimate(unittest.TestCase):
    """Energy is the lifetime token ceiling split by the measured counter mix.

    The split matters: a generated token costs far more energy than a cache
    read, and this archive is 90% cache reads, so pricing them alike would
    overstate the answer several times over.
    """

    def archive(self, output, cache_read, cache_write, input_=0):
        return {"2026-08-06": {"claude-code": {"turns": 1, "models": {"claude-opus-5": {
            "input": input_, "output": output,
            "cache_read": cache_read, "cache_write": cache_write}}}}}

    def results(self):
        # 100 AI lines on the archived day, so ratio == measured_total / 100.
        return [{"date": "2026-08-06", "agent": "Claude Opus 5",
                 "lines": {"Swift": [100, 0, 0, 0, 0, 0]}}]

    def test_each_counter_is_priced_at_its_own_rate(self):
        # 1,000 of each: 1.0 + 0.1 + 0.02 Wh = 1.12 Wh = 0.00112 kWh.
        t = an.token_summary(self.archive(1000, 1000, 1000), self.results())
        self.assertAlmostEqual(t["energy_kwh"], 0.00112)

    def test_cache_reads_are_far_cheaper_than_generated_tokens(self):
        generated = an.token_summary(self.archive(1000, 0, 0), self.results())
        cached = an.token_summary(self.archive(0, 1000, 0), self.results())
        self.assertAlmostEqual(generated["energy_kwh"] / cached["energy_kwh"], 50.0)

    def test_co2_applies_the_grid_intensity_to_the_energy(self):
        t = an.token_summary(self.archive(1000, 1000, 1000), self.results())
        self.assertAlmostEqual(t["co2_kg"], 0.00112 * an.GRID_G_CO2E_PER_KWH / 1000)

    def test_energy_covers_the_lifetime_ceiling_not_only_measured_days(self):
        # An unarchived AI day doubles the lifetime total, so it must double
        # the energy: the estimate follows the ceiling the page displays.
        results = self.results() + [{"date": "2026-01-24", "agent": "Claude Opus 5",
                                     "lines": {"Swift": [100, 0, 0, 0, 0, 0]}}]
        one_day = an.token_summary(self.archive(1000, 1000, 1000), self.results())
        two_days = an.token_summary(self.archive(1000, 1000, 1000), results)
        self.assertEqual(two_days["lifetime_total"], 2 * one_day["lifetime_total"])
        self.assertAlmostEqual(two_days["energy_kwh"], 2 * one_day["energy_kwh"])


class TestTokensByCommit(unittest.TestCase):
    """A day's tokens, measured or estimated, are attributed to that day's
    AI commits in proportion to the lines each one changed."""

    PER_DAY = [["2026-01-24", 5000, "e"], ["2026-08-06", 4000, "m"], ["2026-08-08", 999, "m"]]

    def results(self):
        return [
            {"index": 0, "date": "2026-08-06", "agent": "Claude Opus 5", "lines": {"Swift": [80, 20, 0, 0, 0, 0]}},
            {"index": 1, "date": "2026-08-06", "agent": "Claude Opus 5", "lines": {"Swift": [200, 100, 0, 0, 0, 0]}},
            {"index": 2, "date": "2026-08-06", "agent": None, "lines": {"Swift": [500, 0, 0, 0, 0, 0]}},
            {"index": 3, "date": "2026-08-06", "agent": an.MISC, "lines": {}},
            {"index": 4, "date": "2026-01-24", "agent": "Claude Opus 4.5", "lines": {"Swift": [50, 0, 0, 0, 0, 0]}},
            {"index": 5, "date": "2026-08-07", "agent": "Claude Opus 5", "lines": {"Swift": [10, 0, 0, 0, 0, 0]}},
            {"index": 6, "date": "2026-08-08", "agent": None, "lines": {"Swift": [10, 0, 0, 0, 0, 0]}},
        ]

    def split(self):
        return an.tokens_by_commit([{"key": "claude-code", "per_day": self.PER_DAY}], self.results())

    def test_a_measured_day_is_split_by_lines_changed(self):
        t = self.split()
        # 4,000 tokens over churn of 100 and 300 lines.
        self.assertEqual((t[0], t[1]), (1000, 3000))

    def test_human_and_merge_commits_get_nothing(self):
        t = self.split()
        self.assertNotIn(2, t)
        self.assertNotIn(3, t)

    def test_an_estimated_day_goes_to_its_ai_commits(self):
        t = self.split()
        self.assertEqual(t[4], 5000)

    def test_a_day_without_tokens_attributes_nothing(self):
        self.assertNotIn(5, self.split())

    def test_measured_tokens_on_a_day_without_ai_churn_stay_unattributed(self):
        self.assertNotIn(6, self.split())


class TestCostEstimate(unittest.TestCase):
    """Measured counters priced per model at API list prices."""

    @staticmethod
    def archive(model, **counters):
        c = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        c.update(counters)
        return {"2026-08-06": {"turns": 1, "models": {model: c}}}

    def test_each_counter_at_its_own_rate(self):
        # Opus 5: $5 input, $10 one-hour cache write, $0.50 cache read, $25 output per MTok.
        a = self.archive("claude-opus-5", input=1_000_000, cache_write=1_000_000, cache_read=1_000_000, output=1_000_000)
        self.assertAlmostEqual(an.cost_estimate(a)["measured_usd"], 5 + 10 + 0.5 + 25)

    def test_cache_reads_are_cheaper_on_fable_5_1_than_on_fable_5(self):
        self.assertAlmostEqual(an.cost_estimate(self.archive("claude-fable-5-1", cache_read=1_000_000))["measured_usd"], 0.25)
        self.assertAlmostEqual(an.cost_estimate(self.archive("claude-fable-5", cache_read=1_000_000))["measured_usd"], 1.0)

    def test_earlier_generations_price_by_family(self):
        self.assertAlmostEqual(an.cost_estimate(self.archive("claude-opus-4-6", output=1_000_000))["measured_usd"], 25)
        self.assertAlmostEqual(an.cost_estimate(self.archive("claude-sonnet-4-5", input=1_000_000))["measured_usd"], 3)
        self.assertAlmostEqual(an.cost_estimate(self.archive("claude-haiku-4-5-20251001", output=1_000_000))["measured_usd"], 5)

    def test_unknown_models_are_reported_not_guessed(self):
        cost = an.cost_estimate(self.archive("claude-mystery-9", output=1000, cache_read=500))
        self.assertEqual(cost["measured_usd"], 0)
        self.assertEqual(cost["unpriced_tokens"], 1500)

    # Every id the two vendors list for the families Codex CLI and Gemini CLI
    # report, and the row it must be priced by. A variant whose id extends a
    # shorter one's takes the shorter price unless it has a row of its own.
    VARIANTS = (
        ("gpt-6-astra", "gpt-6-astra"),
        ("gpt-5.6-sol", "gpt-5.6-sol"), ("gpt-5.6-terra", "gpt-5.6-terra"), ("gpt-5.6-luna", "gpt-5.6-luna"),
        ("gpt-5.6-cyber", "gpt-5.6-cyber"),
        ("gpt-5.5", "gpt-5.5"), ("gpt-5.5-pro", "gpt-5.5-pro"), ("gpt-5.5-cyber", "gpt-5.5-cyber"),
        ("gpt-5.4", "gpt-5.4"), ("gpt-5.4-mini", "gpt-5.4-mini"), ("gpt-5.4-nano", "gpt-5.4-nano"),
        ("gpt-5.4-pro", "gpt-5.4-pro"),
        ("gpt-5.3-codex", "gpt-5.3-codex"),
        ("gpt-5.2", "gpt-5.2"), ("gpt-5.2-pro", "gpt-5.2-pro"), ("gpt-5.1", "gpt-5.1"),
        ("gpt-5", "gpt-5"), ("gpt-5-mini", "gpt-5-mini"), ("gpt-5-nano", "gpt-5-nano"), ("gpt-5-pro", "gpt-5-pro"),
        ("gpt-5-search-api", "gpt-5"),                              # listed at gpt-5's price
        ("gpt-5-mini-2025-08-07", "gpt-5-mini"),                    # a dated snapshot
        ("gemini-3.8-flash", "gemini-3.8-flash"), ("gemini-3.7-flash", "gemini-3.7-flash"),
        ("gemini-3.6-flash", "gemini-3.6-flash"),
        ("gemini-3.5-flash", "gemini-3.5-flash"), ("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
        ("gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
        ("gemini-3.1-pro-preview-customtools", "gemini-3.1-pro-preview"),   # listed together
        ("gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
        ("gemini-3-flash-preview", "gemini-3-flash-preview"),
        ("gemini-2.5-pro", "gemini-2.5-pro"), ("gemini-2.5-flash", "gemini-2.5-flash"),
        ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
        ("gpt-5.6", None), ("gpt-4o", None), ("o3", None), ("gemini-3.5", None), ("gemini-3-pro-preview", None),
        # Variants the pages do not list: another model, not a dated copy.
        ("gpt-5.1-codex-mini", None), ("gpt-5-codex", None), ("gpt-5.3-codex-spark", None),
        ("gemini-2.5-flash-image", None), ("gemini-2.5-flash-preview-tts", None),
        ("claude-sonnet-4-5-20250929", "claude-sonnet-4"),
    )

    def test_each_variant_resolves_to_its_own_row(self):
        for model, row in self.VARIANTS:
            with self.subTest(model=model):
                self.assertIs(an.price_for(model), an.PRICE_USD_PER_MTOK[row] if row else None)

    def test_openai_cache_writes_have_their_own_rate(self):
        # gpt-5.6-sol: $4 input, $5 cache write, $0.40 cached input, $20 output per MTok.
        a = self.archive("gpt-5.6-sol", input=1_000_000, cache_write=1_000_000, cache_read=1_000_000, output=1_000_000)
        self.assertAlmostEqual(an.cost_estimate(a)["measured_usd"], 4 + 5 + 0.4 + 20)

    def test_gemini_is_priced_at_its_base_tier(self):
        # gemini-2.5-pro up to 200k tokens: $1.25 input, $0.125 cached, $10 output.
        a = self.archive("gemini-2.5-pro", input=1_000_000, cache_read=1_000_000, output=1_000_000)
        self.assertAlmostEqual(an.cost_estimate(a)["measured_usd"], 1.25 + 0.125 + 10)

    def test_a_scheduled_price_change_applies_from_its_date(self):
        before = self.archive("gemini-3.8-flash", input=1_000_000, output=1_000_000)
        after = {"2027-01-01": before["2026-08-06"]}
        self.assertAlmostEqual(an.cost_estimate(before)["measured_usd"], 0.75 + 3.75)
        self.assertAlmostEqual(an.cost_estimate(after)["measured_usd"], 1.50 + 7.50)
        self.assertEqual(an.price_for("gemini-3.7-flash", "2026-12-31")["cache_read"], 0.075)
        self.assertEqual(an.price_for("gemini-3.7-flash", "2027-01-01")["cache_read"], 0.15)
        self.assertIs(an.price_for("gemini-3.5-flash", "2027-06-01"), an.PRICE_USD_PER_MTOK["gemini-3.5-flash"])

    def test_empty_archive_costs_nothing(self):
        self.assertEqual(an.cost_estimate({}), {"measured_usd": 0.0, "unpriced_tokens": 0})


class TestChurnByDate(unittest.TestCase):
    def test_counts_every_commits_lines_whoever_wrote_them(self):
        results = [
            {"date": "2026-05-01", "agent": "Claude Opus 4.8", "lines": {"Swift": [3, 1, 0, 0, 0, 0]}},
            {"date": "2026-05-01", "agent": None, "lines": {"Swift": [10, 0, 0, 0, 0, 0]}},
            {"date": "2026-05-01", "agent": an.MISC, "lines": {}},
            {"date": "", "agent": None, "lines": {"Swift": [99, 0, 0, 0, 0, 0]}},
        ]
        self.assertEqual(an.churn_by_date(results), {"2026-05-01": 14})


class TestPerSource(unittest.TestCase):
    """Each source's tokens belong to its own agents' commits and nobody else's."""

    @staticmethod
    def entry(output, model="claude-opus-5"):
        return {"turns": 1, "models": {model: {"input": 0, "output": output, "cache_read": 0, "cache_write": 0}}}

    @staticmethod
    def row(index, date, agent, lines):
        return {"index": index, "date": date, "agent": agent, "lines": {"Swift": [lines, 0, 0, 0, 0, 0]}}

    def probe(self):
        # The case that exposed the bug: a Claude and a Cursor commit on a
        # measured day, and a Devin commit on a day with no logs.
        archive = {"2026-09-01": {"claude-code": self.entry(1000)}}
        results = [self.row(0, "2026-09-01", "Claude Opus 5", 50),
                   self.row(1, "2026-09-01", "Cursor", 50),
                   self.row(2, "2026-08-01", "Devin", 50)]
        return archive, results

    def test_commits_by_agents_without_logs_are_counted_and_named(self):
        t = an.token_summary(*self.probe())
        self.assertEqual((t["unmeasured_agent_commits"], t["unmeasured_agents"]), (2, ["Cursor", "Devin"]))

    def test_a_known_source_with_no_logs_is_named_once_by_its_label(self):
        results = [self.row(0, "2026-09-01", "Claude Opus 5", 50),
                   self.row(1, "2026-09-02", "Claude Opus 4.6", 5),
                   self.row(2, "2026-09-02", an.MISC, 0),
                   self.row(3, "2026-09-02", None, 9)]
        t = an.token_summary({}, results)
        self.assertEqual((t["unmeasured_agent_commits"], t["unmeasured_agents"]), (2, ["Claude Code"]))

    def test_a_source_whose_logs_cover_none_of_its_commits_leaves_them_unmeasured(self):
        # Claude Code has a record, but only for a day without a Claude
        # commit, so it has no rate to estimate the Claude commit's day at.
        archive = {"2026-08-10": {"claude-code": self.entry(100)}}
        results = [self.row(0, "2026-08-01", "Claude Opus 5", 10), self.row(1, "2026-08-10", None, 5)]
        t = an.token_summary(archive, results)
        self.assertEqual(an.tokens_by_commit(t["sources"], results), {})
        self.assertEqual((t["unmeasured_agent_commits"], t["unmeasured_agents"]), (1, ["Claude Code"]))

    def test_a_source_whose_records_hold_no_tokens_leaves_its_commits_unmeasured(self):
        # Archives written before the readers dropped zero-usage turns hold
        # Claude Code records of "<synthetic>" turns only. Such a record
        # measured nothing: the source is not listed, and its commits are
        # unmeasured rather than measured at zero.
        archive = {"2026-01-01": {"claude-code": self.entry(0, model="<synthetic>")}}
        results = [self.row(0, "2026-01-01", "Claude Opus 5", 10), self.row(1, "2026-01-02", "Claude Opus 5", 10)]
        t = an.token_summary(archive, results)
        self.assertEqual((t["sources"], t["per_day"], t["measured_days"], t["coverage_start"]), ([], [], 0, None))
        self.assertEqual((an.tokens_by_commit(t["sources"], results), an.token_kinds(t["sources"], results)), ({}, {}))
        self.assertEqual((t["unmeasured_agent_commits"], t["unmeasured_agents"]), (2, ["Claude Code"]))
        self.assertEqual(t["ratio"], 0.0)

    def test_a_day_whose_record_holds_no_tokens_is_estimated_like_a_day_without_one(self):
        archive = {"2026-01-01": {"claude-code": self.entry(1000)},
                   "2026-01-02": {"claude-code": self.entry(0, model="<synthetic>"), "codex": self.entry(0)}}
        results = [self.row(0, "2026-01-01", "Claude Opus 5", 10), self.row(1, "2026-01-02", "Claude Opus 5", 5)]
        t = an.token_summary(archive, results)
        self.assertEqual(t["per_day"], [["2026-01-01", 1000, "m"], ["2026-01-02", 500, "e"]])
        self.assertEqual((t["measured_days"], [s["key"] for s in t["sources"]]), (1, ["claude-code"]))
        self.assertEqual(t["sources"][0]["measured_days"], 1)
        self.assertEqual(an.token_kinds(t["sources"], results), {0: "m", 1: "e"})

    def test_the_ratio_counts_only_the_sources_own_lines(self):
        self.assertEqual(an.token_summary(*self.probe())["ratio"], 20.0)   # not 1,000 over 100 lines

    def test_other_agents_commits_get_none_of_its_tokens(self):
        archive, results = self.probe()
        t = an.token_summary(archive, results)
        self.assertEqual(an.tokens_by_commit(t["sources"], results), {0: 1000})

    def test_an_agent_without_logs_is_not_estimated_at_another_agents_ratio(self):
        t = an.token_summary(*self.probe())
        self.assertEqual(t["per_day"], [["2026-09-01", 1000, "m"]])
        self.assertEqual(t["estimated_total"], 0)

    def test_a_source_is_summarised_on_its_own(self):
        archive, results = self.probe()
        archive["2026-09-01"]["claude-code"]["models"]["claude-fable-5-1"] = {
            "input": 0, "output": 10, "cache_read": 0, "cache_write": 0}
        t = an.token_summary(archive, results)
        self.assertEqual(t["sources"], [{
            "key": "claude-code", "label": "Claude Code", "measured_total": 1010, "measured_days": 1,
            "estimated_total": 0, "ratio": 20.2, "coverage_start": "2026-09-01",
            "top_model": "claude-opus-5", "per_day": [["2026-09-01", 1010, "m"]]}])

    def test_each_commit_takes_the_kind_of_its_own_sources_day(self):
        fake = types.SimpleNamespace(KEY="fake", LABEL="Fake", AGENT=re.compile(r"^Cursor\b"))
        archive = {"2026-08-01": {"fake": self.entry(300)},
                   "2026-09-01": {"claude-code": self.entry(1000), "fake": self.entry(300)}}
        results = [self.row(0, "2026-08-01", "Claude Opus 5", 50),    # estimated for Claude Code
                   self.row(1, "2026-08-01", "Cursor", 10),           # measured for the other source
                   self.row(2, "2026-09-01", "Claude Opus 5", 50),
                   self.row(3, "2026-09-01", "Cursor", 10),
                   self.row(4, "2026-09-01", None, 10)]
        with mock.patch.object(src, "SOURCES", src.SOURCES + (fake,)):
            t = an.token_summary(archive, results)
            kinds = an.token_kinds(t["sources"], results)
            split = an.tokens_by_commit(t["sources"], results)
        self.assertEqual(t["per_day"][0], ["2026-08-01", 1300, "e"])      # the day's total is an estimate
        self.assertEqual(kinds, {0: "e", 1: "m", 2: "m", 3: "m"})
        self.assertEqual(split, {0: 1000, 1: 300, 2: 1000, 3: 300})

    def test_two_sources_on_one_day_each_split_across_their_own_commits(self):
        fake = types.SimpleNamespace(KEY="fake", LABEL="Fake", AGENT=re.compile(r"^Cursor\b"))
        archive = {"2026-09-01": {"claude-code": self.entry(1000), "fake": self.entry(300)}}
        results = [self.row(0, "2026-09-01", "Claude Opus 5", 50),
                   self.row(1, "2026-09-01", "Cursor", 10),
                   self.row(2, "2026-09-01", "Cursor", 20)]
        with mock.patch.object(src, "SOURCES", src.SOURCES + (fake,)):
            t = an.token_summary(archive, results)
            split = an.tokens_by_commit(t["sources"], results)
        self.assertEqual(split, {0: 1000, 1: 100, 2: 200})
        self.assertEqual([(s["key"], s["ratio"]) for s in t["sources"]], [("claude-code", 20.0), ("fake", 10.0)])
        self.assertEqual(t["per_day"], [["2026-09-01", 1300, "m"]])
        self.assertAlmostEqual(t["ratio"], 1300 / 80)

    def test_a_day_with_any_estimated_share_is_an_estimate(self):
        archive = {"2026-08-01": {"future-agent": self.entry(300)},
                   "2026-09-01": {"claude-code": self.entry(1000)}}
        results = [self.row(0, "2026-08-01", "Claude Opus 5", 50),
                   self.row(1, "2026-09-01", "Claude Opus 5", 50)]
        t = an.token_summary(archive, results)
        # Claude Code's 1,000 estimated tokens plus the other source's 300 measured ones.
        self.assertEqual(t["per_day"], [["2026-08-01", 1300, "e"], ["2026-09-01", 1000, "m"]])

    def test_a_source_this_version_does_not_know_is_measured_but_lands_on_no_commit(self):
        archive = {"2026-09-01": {"claude-code": self.entry(1000), "future-agent": self.entry(300)}}
        results = [self.row(0, "2026-09-01", "Claude Opus 5", 50)]
        t = an.token_summary(archive, results)
        self.assertEqual(t["measured_total"], 1300)
        self.assertEqual([(s["key"], s["label"], s["ratio"]) for s in t["sources"]],
                         [("claude-code", "Claude Code", 20.0), ("future-agent", "future-agent", 0.0)])
        # The blended ratio leaves out tokens that land on no lines, so it
        # stays the rate the estimates were actually made at.
        self.assertEqual(t["ratio"], 20.0)
        self.assertEqual(an.tokens_by_commit(t["sources"], results), {0: 1000})
