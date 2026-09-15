import json
import os
import shutil
import tempfile
import unittest

from clocwork import analyse as an
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
        cls.data = an.analyse(cls.tmp.name, cls.out, cls.cache, log=lambda *a: None)

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
            an.analyse(self.tmp.name, self.out, self.cache, log=lambda *a: None)
        finally:
            an.cl.diff_commit = original
        self.assertEqual(calls, [])

    def test_cap_marks_pending(self):
        with tempfile.TemporaryDirectory() as d:
            hashes = fx.make_repo(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), max_commits=1, log=lambda *a: None)
            self.assertEqual([c["status"] for c in data["commits"]], ["ok", "pending", "pending", "merge"])
            self.assertEqual(data["summary"]["pending_commits"], 2)

    def test_every_commit_carries_a_tokens_figure(self):
        # Zero when nothing is attributed, so the page can rely on the key.
        self.assertTrue(all(isinstance(c["tokens"], int) for c in self.data["commits"]))

    def test_summary_carries_a_tokens_block(self):
        t = self.data["summary"]["tokens"]
        self.assertEqual(t["measured_total"], 0)      # no transcripts for the fixture repo
        self.assertEqual(t["per_day"], [])


@unittest.skipUnless(HAVE_CLOC, "cloc not installed")
class TestNonPrMerge(unittest.TestCase):
    def test_multi_parent_commit_is_a_merge(self):
        with tempfile.TemporaryDirectory() as d:
            fx.make_repo(d)
            extra, merge = fx.add_branch_merge(d)
            data = an.analyse(d, os.path.join(d, "o.json"), os.path.join(d, "c.json"), log=lambda *a: None)
            by_hash = {c["full_hash"]: c for c in data["commits"]}
            self.assertEqual(by_hash[extra]["lines"], {"Markdown": [1, 0, 0, 0, 0, 0]})
            self.assertEqual(by_hash[merge]["status"], "merge")
            self.assertEqual(by_hash[merge]["agent"], "Misc")
            self.assertEqual(by_hash[merge]["lines"], {})
            zero = {"code": 0, "comment": 0, "blank": 0}
            self.assertEqual(data["summary"]["reconciliation"]["Markdown"], zero)   # no double counting
            self.assertEqual(data["summary"]["misc_commits"], 2)


class TestMissingCloc(unittest.TestCase):
    def test_raises_before_touching_git(self):
        real = shutil.which
        shutil.which = lambda name: None
        try:
            with self.assertRaises(an.cl.ClocMissing):
                an.analyse("/definitely/not/a/repo", "/dev/null")
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
        return {"2026-08-06": {"turns": 3, "models": {"claude-opus-5": {
            "input": 0, "output": 500, "cache_read": 4500, "cache_write": 0}}}}

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
        return {"2026-08-06": {"turns": 1, "models": {"claude-opus-5": {
            "input": input_, "output": output,
            "cache_read": cache_read, "cache_write": cache_write}}}}

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

    def test_a_measured_day_is_split_by_lines_changed(self):
        t = an.tokens_by_commit(self.PER_DAY, self.results())
        # 4,000 tokens over churn of 100 and 300 lines.
        self.assertEqual((t[0], t[1]), (1000, 3000))

    def test_human_and_merge_commits_get_nothing(self):
        t = an.tokens_by_commit(self.PER_DAY, self.results())
        self.assertNotIn(2, t)
        self.assertNotIn(3, t)

    def test_an_estimated_day_goes_to_its_ai_commits(self):
        t = an.tokens_by_commit(self.PER_DAY, self.results())
        self.assertEqual(t[4], 5000)

    def test_a_day_without_tokens_attributes_nothing(self):
        self.assertNotIn(5, an.tokens_by_commit(self.PER_DAY, self.results()))

    def test_measured_tokens_on_a_day_without_ai_churn_stay_unattributed(self):
        self.assertNotIn(6, an.tokens_by_commit(self.PER_DAY, self.results()))


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

    def test_empty_archive_costs_nothing(self):
        self.assertEqual(an.cost_estimate({}), {"measured_usd": 0.0, "unpriced_tokens": 0})


class TestChurnByDate(unittest.TestCase):
    def test_splits_ai_churn_from_total_churn(self):
        results = [
            {"date": "2026-05-01", "agent": "Claude Opus 4.8", "lines": {"Swift": [3, 1, 0, 0, 0, 0]}},
            {"date": "2026-05-01", "agent": None, "lines": {"Swift": [10, 0, 0, 0, 0, 0]}},
            {"date": "2026-05-01", "agent": an.MISC, "lines": {}},
        ]
        churn = an.churn_by_date(results)
        self.assertEqual(churn["2026-05-01"], {"churn": 14, "ai_churn": 4})
