import os
import unittest

from clocwork import tokens as tu
from clocwork.sources import copilot


def usage(input=0, output=0, cache_read=0, cache_write=0, reasoning=0):
    """A metric's usage as Copilot writes it: inputTokens already contains
    both cache buckets, so it is given here as the uncached input plus them."""
    return {"inputTokens": input + cache_read + cache_write, "outputTokens": output,
            "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write, "reasoningTokens": reasoning}


def metric(input=0, output=0, cache_read=0, cache_write=0, reasoning=0, requests=1, details=True):
    """One model's row of a session.shutdown's modelMetrics."""
    m = {"requests": {"count": requests, "cost": 0},
         "usage": usage(input, output, cache_read, cache_write, reasoning)}
    if details:
        m["tokenDetails"] = {"input": {"tokenCount": input}, "output": {"tokenCount": output},
                             "cache_read": {"tokenCount": cache_read}}
        if cache_write:
            m["tokenDetails"]["cache_write"] = {"tokenCount": cache_write}
    return m


def counts(input=0, output=0, cache_read=0, cache_write=0):
    return {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write}


class TestHomes(unittest.TestCase):
    def test_copilot_home_replaces_the_default(self):
        self.assertEqual(copilot.default_homes({"COPILOT_HOME": "/h"}), [os.path.join("/h", "session-state")])

    def test_the_default_is_under_the_home_directory(self):
        self.assertEqual(copilot.default_homes({}),
                         [os.path.expanduser(os.path.join("~", ".copilot", "session-state"))])


class TestCounters(unittest.TestCase):
    def test_the_cache_buckets_come_out_of_the_input(self):
        # inputTokens = 10,547 = 8,883 uncached + 1,664 read, as recorded.
        self.assertEqual(copilot.counters(metric(8_883, 76, cache_read=1_664)),
                         counts(8_883, 76, cache_read=1_664))

    def test_a_cache_write_comes_out_of_the_input_too(self):
        # inputTokens = 12,612 = 10 uncached + 12,602 written, as recorded.
        self.assertEqual(copilot.counters(metric(10, 35, cache_write=12_602)),
                         counts(10, 35, cache_write=12_602))

    def test_reasoning_is_already_inside_the_output(self):
        # Every recorded row has tokenDetails.output equal to outputTokens
        # with no reasoning bucket, so reasoningTokens is not added.
        self.assertEqual(copilot.counters(metric(10, 76, reasoning=64))["output"], 76)

    def test_a_count_that_is_not_a_number_is_zero(self):
        m = {"usage": {"inputTokens": "many", "outputTokens": 10, "cacheReadTokens": None,
                       "cacheWriteTokens": 2.5, "reasoningTokens": 1}}
        self.assertEqual(copilot.counters(m), counts(0, 10))

    def test_nothing_goes_below_zero(self):
        m = {"usage": {"inputTokens": 10, "outputTokens": -4, "cacheReadTokens": 30, "cacheWriteTokens": 0}}
        self.assertEqual(copilot.counters(m), counts(0, 0, cache_read=30))

    def test_a_usage_that_is_not_an_object_counts_nothing(self):
        self.assertEqual(copilot.counters({"usage": ["not", "usage"]}), counts())


class TestOwnUncachedInput(unittest.TestCase):
    """tokenDetails.input.tokenCount is the uncached input, which every
    recorded row agrees with; a disagreement means the format moved."""

    def test_the_recorded_figure_is_read(self):
        self.assertEqual(copilot.uncached(metric(8_883, 76, cache_read=1_664)), 8_883)

    def test_a_metric_that_reports_none_is_not_checked(self):
        self.assertIsNone(copilot.uncached(metric(10, 5, details=False)))

    def test_a_figure_that_is_not_a_number_is_not_checked(self):
        for value in ("8883", None, 1.5, True, {"tokenCount": 1}):
            with self.subTest(value=value):
                m = metric(10, 5)
                m["tokenDetails"]["input"]["tokenCount"] = value
                self.assertIsNone(copilot.uncached(m))

    def test_token_details_that_is_not_an_object_is_not_checked(self):
        self.assertIsNone(copilot.uncached({"tokenDetails": ["input"]}))
        self.assertIsNone(copilot.uncached({"tokenDetails": {"input": 8_883}}))


class TestIncrease(unittest.TestCase):
    """A shutdown's counters are cumulative for the session so far, so what
    a snapshot adds is its increase over the largest one seen before it."""

    def test_the_first_snapshot_is_its_own_increase(self):
        self.assertEqual(copilot.increase(None, (counts(10, 5), 1)), (counts(10, 5), 1))

    def test_a_repeated_snapshot_adds_nothing(self):
        seen = (counts(10, 5), 1)
        self.assertEqual(copilot.increase(seen, seen), (counts(), 0))

    def test_only_what_a_later_snapshot_adds_is_counted(self):
        seen = (counts(10, 5, cache_read=2), 1)
        now = (counts(30, 9, cache_read=2, cache_write=4), 3)
        self.assertEqual(copilot.increase(seen, now), (counts(20, 4, cache_write=4), 2))

    def test_a_counter_that_goes_backwards_is_no_increase(self):
        seen = (counts(10, 5), 1)
        for now in (counts(9, 5), counts(10, 4), counts(10, 5, cache_read=-1)):
            with self.subTest(now=now):
                self.assertIsNone(copilot.increase(seen, (now, 1)))

    def test_a_request_count_that_goes_backwards_is_no_increase(self):
        self.assertIsNone(copilot.increase((counts(10, 5), 2), (counts(10, 5), 1)))


class TestRepository(unittest.TestCase):
    """Copilot records the repository it ran on as owner/name beside its
    host, which is the identity paths.remote_key builds."""

    def context(self, **over):
        base = {"cwd": "/work/repo/sub", "gitRoot": "/work/repo", "repository": "example/app",
                "repositoryHost": "github.com", "headCommit": "a" * 40, "baseCommit": "b" * 40}
        base.update(over)
        return base

    def test_the_recorded_host_and_repository_make_a_remote_key(self):
        self.assertEqual(copilot.session_remote(self.context()), "github.com/example/app")

    def test_a_host_written_in_capitals_is_lowered(self):
        self.assertEqual(copilot.session_remote(self.context(repositoryHost="GitHub.COM")), "github.com/example/app")

    def test_without_both_there_is_no_key(self):
        for over in ({"repositoryHost": None}, {"repository": None}, {"repository": "app"},
                     {"repository": ""}, {"repositoryHost": 7}):
            with self.subTest(over=over):
                self.assertIsNone(copilot.session_remote(self.context(**over)))

    def test_the_working_directory_or_the_git_root_counts_as_inside(self):
        for over in ({}, {"cwd": "/elsewhere"}, {"gitRoot": "/elsewhere"}, {"gitRoot": "/work/repo/sub"}):
            with self.subTest(over=over):
                self.assertTrue(copilot.ran_inside(self.context(**over), "/work/repo"))

    def test_neither_inside_is_outside(self):
        self.assertFalse(copilot.ran_inside(self.context(cwd="/elsewhere", gitRoot="/other"), "/work/repo"))

    def test_a_sibling_whose_name_starts_the_same_is_outside(self):
        self.assertFalse(copilot.ran_inside(self.context(cwd="/work/repo-stats", gitRoot="/work/repo-stats"),
                                            "/work/repo"))

    def test_a_missing_path_is_outside(self):
        self.assertFalse(copilot.ran_inside({}, "/work/repo"))
        self.assertFalse(copilot.ran_inside({"cwd": 7, "gitRoot": ""}, "/work/repo"))

    def test_the_same_remote_belongs_from_any_clone(self):
        never = lambda _sha: False
        self.assertTrue(copilot.belongs(self.context(cwd="/elsewhere", gitRoot="/elsewhere"),
                                        "/work/repo", "github.com/example/app", never))

    def test_a_remote_that_differs_belongs_only_from_a_commit_of_the_repository(self):
        inside = self.context()
        self.assertTrue(copilot.belongs(inside, "/work/repo", "github.com/example/renamed", lambda sha: sha == "a" * 40))
        self.assertTrue(copilot.belongs(inside, "/work/repo", "github.com/example/renamed", lambda sha: sha == "b" * 40))
        self.assertFalse(copilot.belongs(inside, "/work/repo", "github.com/example/renamed", lambda _sha: False))

    def test_a_remote_that_differs_never_belongs_from_outside(self):
        outside = self.context(cwd="/elsewhere", gitRoot="/elsewhere")
        self.assertFalse(copilot.belongs(outside, "/work/repo", "github.com/example/other", lambda _sha: True))

    def test_without_two_remotes_the_directory_decides(self):
        never = lambda _sha: False
        self.assertTrue(copilot.belongs(self.context(repository=None), "/work/repo", "github.com/example/app", never))
        self.assertTrue(copilot.belongs(self.context(), "/work/repo", None, never))
        self.assertFalse(copilot.belongs(self.context(cwd="/elsewhere", gitRoot="/elsewhere", repository=None),
                                         "/work/repo", "github.com/example/app", never))


class TestSourceContract(unittest.TestCase):
    def test_the_module_provides_what_a_source_must(self):
        for name in ("KEY", "LABEL", "AGENT", "default_homes", "scan"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(copilot, name))

    def test_its_agent_pattern_matches_the_name_the_matcher_produces(self):
        self.assertTrue(copilot.AGENT.search("Copilot"))

    def test_the_counters_it_reports_are_the_archive_s_own(self):
        self.assertEqual(sorted(copilot.counters(metric(1, 1))), sorted(tu.COUNTERS))


if __name__ == "__main__":
    unittest.main()
