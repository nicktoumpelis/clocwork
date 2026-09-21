import json
import os
import shutil
import tempfile
import unittest

from clocwork import tokens as tu
from clocwork.sources import copilot
from tests import agent_logs
from tests import repo_fixture as fx

# The two Irrlicht recordings, computed before reduction and without the
# reader: each shutdown's own uncached input, cache buckets and output, with a
# resumed session's repeated rows counted once.
RECORDED = {
    "2026-08-03": {"turns": 2, "models": {
        "gpt-5-mini": {"input": 9_318, "output": 165, "cache_read": 11_776, "cache_write": 0}}},
    "2026-08-05": {"turns": 2, "models": {
        "claude-haiku-4.5": {"input": 10, "output": 35, "cache_read": 0, "cache_write": 12_602},
        "gpt-5-mini": {"input": 9_277, "output": 88, "cache_read": 1_536, "cache_write": 0}}},
}
# The sessions those recordings hold: two that called a model on 2026-08-03,
# one that called none, and one resumed and recorded twice on 2026-08-05.
CALLED = "5920fe71-13c6-431f-8545-13bb327e3fa1"
NO_MODEL = "144d0848-1ca0-49df-a61f-59fe01d4f5eb"
RESUMED = "aa737378-7ebd-4c0b-9c77-77c050d2df98"


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

    def test_a_row_that_agrees_with_itself_agrees(self):
        self.assertTrue(copilot.agrees(metric(8_883, 76, cache_read=1_664)))
        self.assertTrue(copilot.agrees(metric(10, 35, cache_write=12_602)))

    def test_a_row_that_reports_no_figure_of_its_own_is_taken_as_it_stands(self):
        self.assertTrue(copilot.agrees(metric(10, 5, details=False)))
        self.assertTrue(copilot.agrees({}))

    def test_a_row_whose_own_figure_differs_does_not_agree(self):
        m = metric(100, 20, cache_read=5)
        m["tokenDetails"]["input"]["tokenCount"] = 99
        self.assertFalse(copilot.agrees(m))

    def test_an_input_that_has_fallen_below_its_cache_buckets_does_not_agree(self):
        # The derived figure is compared before it is clamped at zero. Read
        # through counters() this row looks consistent -- 100 - 200 clamps to
        # 0, which is what it reports -- and the check would miss the very
        # change it is there to catch.
        m = {"usage": {"inputTokens": 100, "outputTokens": 5, "cacheReadTokens": 200, "cacheWriteTokens": 0},
             "tokenDetails": {"input": {"tokenCount": 0}}}
        self.assertEqual(copilot.counters(m)["input"], 0)
        self.assertEqual(copilot.uncached(m), 0)
        self.assertFalse(copilot.agrees(m))


class TestIncrease(unittest.TestCase):
    """A shutdown's counters are cumulative for the session so far, so what
    a snapshot adds is its increase over the largest one seen before it.
    A snapshot no counter of which has grown is already covered by a larger
    one and adds nothing; only one grown in a counter and fallen in another
    is counted against the log."""

    def test_the_first_snapshot_is_its_own_increase(self):
        self.assertEqual(copilot.increase(None, (counts(10, 5), 1)), (counts(10, 5), 1))

    def test_only_what_a_later_snapshot_adds_is_counted(self):
        seen = (counts(10, 5, cache_read=2), 1)
        now = (counts(30, 9, cache_read=2, cache_write=4), 3)
        self.assertEqual(copilot.increase(seen, now), (counts(20, 4, cache_write=4), 2))

    def test_a_snapshot_no_counter_of_which_has_grown_is_stale(self):
        # A log that repeats a block, or two files holding one session,
        # replay snapshots already read. They add nothing, and saying so is
        # not the same as saying the log is damaged.
        seen = (counts(10, 5), 1)
        for now in (counts(10, 5), counts(9, 5), counts(10, 4), counts(), counts(10, 5, cache_read=-1)):
            with self.subTest(now=now):
                self.assertIs(copilot.increase(seen, (now, 1)), copilot.STALE)

    def test_a_snapshot_grown_in_one_counter_and_fallen_in_another_is_broken(self):
        seen = (counts(10, 5, cache_read=4), 1)
        for now in (counts(20, 4, cache_read=4), counts(10, 9, cache_read=1), counts(20, 5)):
            with self.subTest(now=now):
                self.assertIs(copilot.increase(seen, (now, 1)), copilot.BROKEN)

    def test_a_request_count_that_goes_backwards_does_not_discard_the_tokens(self):
        # The request count measures turns, not tokens. Tokens cannot be
        # recovered once a log expires; an understated turn count loses
        # nothing, so the count never decides whether a row is read.
        self.assertEqual(copilot.increase((counts(10, 5), 2), (counts(30, 9), 1)),
                         (counts(20, 4), 0))

    def test_a_request_count_that_has_not_moved_adds_no_calls(self):
        self.assertEqual(copilot.increase((counts(10, 5), 4), (counts(30, 9), 4))[1], 0)

    def test_a_row_reporting_no_request_count_leaves_the_calls_unknown(self):
        self.assertIsNone(copilot.increase((counts(10, 5), 4), (counts(30, 9), None))[1])

    def test_the_largest_seen_keeps_a_request_count_a_later_row_omits(self):
        # Otherwise the next row that does report one would look like a leap
        # from zero and count every call of the session again.
        self.assertEqual(copilot.largest((counts(10, 5), 4), (counts(30, 9), None)),
                         (counts(30, 9), 4))
        self.assertEqual(copilot.largest((counts(10, 5), 4), (counts(30, 9), 6)),
                         (counts(30, 9), 6))


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


def context(repo, **over):
    base = {"cwd": repo, "gitRoot": repo, "repository": "example/agent-sample",
            "repositoryHost": "github.com", "headCommit": "a" * 40, "baseCommit": "b" * 40}
    base.update(over)
    return base


def start(repo, sid="s1", ts="2026-08-05T10:00:00.000Z", version="1.0.78", **over):
    return {"type": "session.start", "timestamp": ts,
            "data": {"sessionId": sid, "copilotVersion": version, "startTime": ts,
                     "context": context(repo, **over)}}


def resume(repo, ts="2026-08-05T11:00:00.000Z", **over):
    return {"type": "session.resume", "timestamp": ts,
            "data": {"resumeTime": ts, "context": context(repo, **over)}}


def shutdown(metrics, ts="2026-08-05T12:00:00.000Z"):
    return {"type": "session.shutdown", "timestamp": ts,
            "data": {"shutdownType": "routine", "modelMetrics": metrics}}


class TestRecordings(unittest.TestCase):
    """The reduced Copilot CLI recordings in tests/fixtures/copilot, read
    where Copilot writes them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "agent-sample")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".copilot")

    def install(self, repo=None, remote=agent_logs.REMOTE):
        return agent_logs.install("copilot", self.home, repo or self.repo, remote=remote)

    def scan(self, repo=None):
        return copilot.scan(repo or self.repo, copilot.default_homes({"COPILOT_HOME": self.home}))

    def keep(self, *sessions):
        """Leave only these sessions' logs installed."""
        for name in os.listdir(os.path.join(self.home, "session-state")):
            if name not in sessions:
                shutil.rmtree(os.path.join(self.home, "session-state", name))

    def test_every_recorded_day_and_model(self):
        self.install()
        result = self.scan()
        self.assertEqual(result.days, RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_the_session_recorded_twice_is_counted_once(self):
        # The recording holds the resumed session's whole block twice. The
        # same log with the repetition cut out must read the same, which is
        # what "read the increase" buys.
        self.install()
        self.keep(RESUMED)
        twice = self.scan().days
        log = os.path.join(self.home, "session-state", RESUMED, "events.jsonl")
        with open(log, encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        half = len(records) // 2
        self.assertEqual(records[:half], records[half:])       # it really is written twice
        with open(log, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in records[:half]))
        self.assertEqual(twice, self.scan().days)
        self.assertEqual(twice, {"2026-08-05": RECORDED["2026-08-05"]})

    def test_the_two_snapshots_of_a_resumed_session_are_not_summed(self):
        # Both snapshots report the haiku row at 12,612 input tokens; summing
        # the four recorded snapshots would report 50,448.
        self.install()
        self.keep(RESUMED)
        self.assertEqual(self.scan().days["2026-08-05"]["models"]["claude-haiku-4.5"],
                         {"input": 10, "output": 35, "cache_read": 0, "cache_write": 12_602})

    def test_a_session_that_called_no_model_records_nothing(self):
        self.install()
        self.keep(NO_MODEL)
        result = self.scan()
        self.assertEqual((result.days, result.malformed, result.skipped), ({}, 0, 0))

    def test_a_repository_elsewhere_is_not_matched(self):
        self.install()
        self.assertIsNone(self.scan(os.path.join(self.root, "elsewhere", "agent-sample")))

    def test_no_sessions_is_none(self):
        self.assertIsNone(self.scan())

    def test_the_recorded_remote_matches_another_clone_of_it(self):
        # A session that ran on another machine's clone: its paths are
        # nowhere near this one, and only the remote ties it to the
        # repository.
        fx._git(self.repo, "init", "-q", "-b", "main")
        fx._git(self.repo, "remote", "add", "origin", agent_logs.REMOTE)
        self.install(repo=os.path.join(self.root, "another", "clone"))
        self.assertEqual(self.scan().days, RECORDED)

    def test_a_repository_with_another_remote_needs_one_of_its_commits(self):
        fx._git(self.repo, "init", "-q", "-b", "main")
        fx._git(self.repo, "remote", "add", "origin", "https://github.com/example/other.git")
        self.install()
        self.assertIsNone(self.scan())          # ran here, but recorded a remote of its own
        fx._write(self.repo, "a.py", "print()\n")
        fx._git(self.repo, "add", ".")
        fx._git(self.repo, "commit", "-q", "-m", "Initial")
        head = fx._git(self.repo, "rev-parse", "HEAD").strip()
        shutil.rmtree(os.path.join(self.home, "session-state"))
        self.install(repo=self.repo, remote=agent_logs.REMOTE)
        for name in os.listdir(os.path.join(self.home, "session-state")):
            log = os.path.join(self.home, "session-state", name, "events.jsonl")
            with open(log, encoding="utf-8") as f:
                text = f.read()
            with open(log, "w", encoding="utf-8") as f:
                f.write(text.replace("4b58365c0a6b9cec3b67cc1a1483dca08efa0c44", head)
                            .replace("57d59deff3d691fc79c7e7285b92ff9244708108", head))
        self.assertEqual(self.scan().days, RECORDED)


class LogHome(unittest.TestCase):
    """A Copilot home to write hand-made logs into, and the scan of it. It
    holds no tests of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".copilot")

    def write(self, records, session="s1"):
        path = os.path.join(self.home, "session-state", session, "events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records))
        return path

    def scan(self):
        return copilot.scan(self.repo, copilot.default_homes({"COPILOT_HOME": self.home}))

    def day(self, date="2026-08-05"):
        return self.scan().days[date]


class TestRules(LogHome):
    def test_one_snapshot_is_recorded_as_it_stands(self):
        self.write([start(self.repo), shutdown({"m": metric(100, 20, cache_read=5)})])
        self.assertEqual(self.day()["models"]["m"], counts(100, 20, cache_read=5))

    def test_a_second_snapshot_adds_only_its_increase(self):
        self.write([start(self.repo),
                    shutdown({"m": metric(100, 20, cache_read=5)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(250, 33, cache_read=5, cache_write=7)}, "2026-08-05T13:00:00.000Z")])
        self.assertEqual(self.day()["models"]["m"], counts(250, 33, cache_read=5, cache_write=7))

    def test_a_session_resumed_after_midnight_splits_at_the_snapshot(self):
        self.write([start(self.repo, ts="2026-08-05T23:00:00.000Z"),
                    shutdown({"m": metric(100, 20)}, "2026-08-05T23:59:00.000Z"),
                    resume(self.repo, "2026-08-06T00:00:30.000Z"),
                    shutdown({"m": metric(250, 33)}, "2026-08-06T00:01:00.000Z")])
        days = self.scan().days
        self.assertEqual(days["2026-08-05"]["models"]["m"], counts(100, 20))
        self.assertEqual(days["2026-08-06"]["models"]["m"], counts(150, 13))

    def test_counters_that_contradict_being_cumulative_are_counted_not_archived(self):
        # Input up, output down: whatever this row is, it is not the running
        # total the whole reading rests on.
        self.write([start(self.repo),
                    shutdown({"m": metric(100, 20)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(200, 8)}, "2026-08-05T13:00:00.000Z")])
        result = self.scan()
        self.assertEqual(result.days["2026-08-05"]["models"]["m"], counts(100, 20))
        self.assertEqual(result.malformed, 1)

    def test_a_block_repeated_after_its_counts_grew_is_not_counted_as_damage(self):
        # The recorded resume repeats a block whose figures happen to be
        # identical. A block whose counts grew inside it replays snapshots
        # that are behind the running total, which adds nothing and says
        # nothing about the log being damaged.
        block = [start(self.repo),
                 shutdown({"m": metric(100, 20)}, "2026-08-05T12:00:00.000Z"),
                 shutdown({"m": metric(200, 40, requests=2)}, "2026-08-05T13:00:00.000Z")]
        self.write(block + block)
        result = self.scan()
        self.assertEqual(result.days["2026-08-05"]["models"]["m"], counts(200, 40))
        self.assertEqual((result.days["2026-08-05"]["turns"], result.malformed), (2, 0))

    def test_a_snapshot_with_no_day_is_counted_and_its_tokens_are_not_lost(self):
        # The undated snapshot must not advance the running total: if it
        # did, the tokens between it and the row before it would be archived
        # by nothing and reported by nothing.
        self.write([start(self.repo),
                    shutdown({"m": metric(1_000, 100)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(5_000, 500)}, "05/08/2026 13:00"),
                    shutdown({"m": metric(6_000, 600)}, "2026-08-05T14:00:00.000Z")])
        result = self.scan()
        self.assertEqual(result.days["2026-08-05"]["models"]["m"], counts(6_000, 600))
        self.assertEqual(result.malformed, 1)

    def test_a_row_whose_input_has_fallen_below_its_cache_buckets_is_counted(self):
        self.write([start(self.repo), shutdown({"m": {
            "requests": {"count": 1, "cost": 0},
            "usage": {"inputTokens": 100, "outputTokens": 5, "cacheReadTokens": 200, "cacheWriteTokens": 0},
            "tokenDetails": {"input": {"tokenCount": 0}}}})])
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_a_trailing_row_that_reports_no_request_count_keeps_its_tokens(self):
        # A session's last shutdown is its largest, so rejecting a row over
        # its request count would lose the most tokens of any row in it.
        last = metric(2_000, 200)
        del last["requests"]
        self.write([start(self.repo),
                    shutdown({"m": metric(1_000, 100, requests=3)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": last}, "2026-08-05T13:00:00.000Z")])
        result = self.scan()
        day = result.days["2026-08-05"]
        self.assertEqual((day["models"]["m"], day["turns"], result.malformed), (counts(2_000, 200), 4, 0))

    def test_a_row_whose_own_uncached_input_disagrees_is_counted_not_archived(self):
        m = metric(100, 20, cache_read=5)
        m["tokenDetails"]["input"]["tokenCount"] = 99      # inputTokens says 105 - 5 = 100
        self.write([start(self.repo), shutdown({"m": m})])
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_turns_come_from_the_request_count(self):
        self.write([start(self.repo), shutdown({"m": metric(100, 20, requests=4)})])
        self.assertEqual(self.day()["turns"], 4)

    def test_only_the_calls_a_later_snapshot_adds_are_new_turns(self):
        self.write([start(self.repo),
                    shutdown({"m": metric(100, 20, requests=4)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(180, 30, requests=6)}, "2026-08-05T13:00:00.000Z")])
        self.assertEqual(self.day()["turns"], 6)

    def test_a_request_count_that_has_not_moved_adds_no_turn(self):
        # Copilot is taken at its word. It says the session has made one
        # call, so a second snapshot of that one call is not a second turn,
        # even where its tokens have grown -- the floor of one belongs to a
        # row that reports no count at all, not to a row that reports none
        # added.
        self.write([start(self.repo),
                    shutdown({"m": metric(100, 20, requests=1)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(200, 40, requests=1)}, "2026-08-05T13:00:00.000Z")])
        day = self.day()
        self.assertEqual((day["models"]["m"], day["turns"]), (counts(200, 40), 1))

    def test_a_count_reported_again_after_a_row_that_omits_it_adds_only_its_own_calls(self):
        # The count a row omits is carried forward, so the next row that
        # does report one reads as an increase over it. Losing it would make
        # that row a leap from zero and count the session's calls again.
        middle = metric(2_000, 200)
        del middle["requests"]
        self.write([start(self.repo),
                    shutdown({"m": metric(1_000, 100, requests=3)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": middle}, "2026-08-05T13:00:00.000Z"),
                    shutdown({"m": metric(3_000, 300, requests=5)}, "2026-08-05T14:00:00.000Z")])
        day = self.day()
        # 3 reported, 1 for the row that reports none, then 5 - 3 = 2.
        self.assertEqual((day["models"]["m"], day["turns"]), (counts(3_000, 300), 6))

    def test_a_request_count_that_falls_keeps_the_tokens_and_adds_no_turn(self):
        self.write([start(self.repo),
                    shutdown({"m": metric(1_000, 100, requests=4)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(3_000, 300, requests=1)}, "2026-08-05T13:00:00.000Z")])
        result = self.scan()
        day = result.days["2026-08-05"]
        self.assertEqual((day["models"]["m"], day["turns"], result.malformed),
                         (counts(3_000, 300), 4, 0))

    def test_a_row_with_no_request_count_still_counts_one_turn(self):
        m = metric(100, 20)
        del m["requests"]
        self.write([start(self.repo), shutdown({"m": m})])
        self.assertEqual(self.day()["turns"], 1)

    def test_a_shutdown_with_no_model_metrics_records_nothing(self):
        self.write([start(self.repo), {"type": "session.shutdown", "timestamp": "2026-08-05T12:00:00.000Z",
                                       "data": {"shutdownType": "routine"}}])
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 0))

    def test_a_shutdown_with_no_session_before_it_is_ignored(self):
        self.write([shutdown({"m": metric(100, 20)})])
        self.assertIsNone(self.scan())

    def test_a_log_that_opens_with_a_resume_is_read(self):
        self.write([resume(self.repo, "2026-08-05T11:00:00.000Z"), shutdown({"m": metric(100, 20)})])
        self.assertEqual(self.day()["models"]["m"], counts(100, 20))

    def test_two_sessions_in_one_log_are_counted_apart(self):
        self.write([start(self.repo, sid="a"), shutdown({"m": metric(100, 20)}, "2026-08-05T12:00:00.000Z"),
                    start(self.repo, sid="b"), shutdown({"m": metric(100, 20)}, "2026-08-05T13:00:00.000Z")])
        day = self.day()
        self.assertEqual((day["models"]["m"], day["turns"]), (counts(200, 40), 2))

    def test_the_same_session_in_two_logs_is_counted_once(self):
        records = [start(self.repo, sid="a"), shutdown({"m": metric(100, 20)})]
        self.write(records, session="a")
        self.write(records, session="backup-of-a")
        self.assertEqual(self.day()["models"]["m"], counts(100, 20))

    def test_a_copy_of_a_session_that_lost_its_start_is_still_that_session(self):
        # Copilot names a session's directory after its id, so a copy that
        # begins part-way through -- in a backed-up tree, under the same
        # directory name -- belongs to the session that name points at.
        # Keyed by anything else, its whole cumulative total is archived a
        # second time on top of the first.
        self.write([start(self.repo, sid="a"), shutdown({"m": metric(100, 20)})], session="a")
        self.write([resume(self.repo, "2026-08-05T11:00:00.000Z"), shutdown({"m": metric(100, 20)})],
                   session=os.path.join("backup", "a"))
        day = self.day()
        self.assertEqual((day["models"]["m"], day["turns"]), (counts(100, 20), 1))

    def test_a_log_with_no_session_start_reads_its_resumes_as_one_session(self):
        # Nothing but session.start names a session, so a log that begins
        # part-way through one cannot tell a second session from the same one
        # resuming. Reading them as one session is the choice that cannot
        # inflate a total: the second block's snapshot repeats the first's,
        # and a repeat adds nothing.
        records = [resume(self.repo, "2026-08-05T11:00:00.000Z"), shutdown({"m": metric(100, 20)})]
        self.write(records + records)
        self.assertEqual(self.day()["models"]["m"], counts(100, 20))

    def test_two_sessions_that_both_start_unnamed_are_counted_apart(self):
        # A session.start does name a new session, even with no id on it.
        unnamed = start(self.repo)
        del unnamed["data"]["sessionId"]
        self.write([unnamed, shutdown({"m": metric(100, 20)}, "2026-08-05T12:00:00.000Z"),
                    unnamed, shutdown({"m": metric(100, 20)}, "2026-08-05T13:00:00.000Z")])
        self.assertEqual(self.day()["models"]["m"], counts(200, 40))

    def test_a_snapshot_with_no_timestamp_lands_on_no_day(self):
        self.write([start(self.repo), shutdown({"m": metric(100, 20)}, "no date")])
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_a_line_that_is_not_json_is_counted(self):
        self.write([start(self.repo), '{"type": "session.shutdown", "data": {',
                    shutdown({"m": metric(100, 20)})])
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed), (counts(100, 20), 1))

    def test_a_record_of_the_wrong_shape_is_read_as_missing(self):
        for record in ([1, 2, 3],
                       {"type": "session.shutdown", "timestamp": "2026-08-05T12:00:00.000Z", "data": "gone"},
                       {"type": "session.shutdown", "timestamp": "2026-08-05T12:00:00.000Z",
                        "data": {"modelMetrics": ["m"]}},
                       {"type": "session.shutdown", "timestamp": "2026-08-05T12:00:00.000Z",
                        "data": {"modelMetrics": {"m": "gone"}}}):
            with self.subTest(record=record):
                self.write([start(self.repo), record])
                result = self.scan()
                self.assertEqual((result.days, result.malformed, result.skipped), ({}, 0, 0))

    def test_a_context_of_the_wrong_shape_leaves_the_last_one_standing(self):
        self.write([start(self.repo),
                    {"type": "session.resume", "timestamp": "2026-08-05T11:00:00.000Z",
                     "data": {"context": ["gone"]}},
                    shutdown({"m": metric(100, 20)})])
        self.assertEqual(self.day()["models"]["m"], counts(100, 20))

    def test_a_session_from_another_repository_is_not_read(self):
        self.write([start(os.path.join(self.root, "other")), shutdown({"m": metric(100, 20)})])
        self.assertIsNone(self.scan())

    def test_a_log_that_cannot_be_read_is_skipped(self):
        path = self.write([start(self.repo), shutdown({"m": metric(100, 20)})])
        os.remove(path)
        os.symlink(os.path.join(self.root, "gone", "events.jsonl"), path)
        result = self.scan()
        self.assertEqual((result.days, result.malformed, result.skipped), ({}, 0, 1))
        self.assertIn("damaged", copilot.SKIPPED)

    def test_a_log_found_under_two_overlapping_homes_is_read_once(self):
        # Reading one log twice would replay its snapshots and report the
        # second reading as contradicting the first.
        self.write([start(self.repo), shutdown({"m": metric(100, 20)})])
        state = os.path.join(self.home, "session-state")
        self.assertEqual(len(copilot.logs([state, self.home, state])), 1)
        result = copilot.scan(self.repo, [state, self.home])
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed),
                         (counts(100, 20), 0))

    def test_a_log_under_another_name_is_not_read(self):
        path = self.write([start(self.repo), shutdown({"m": metric(100, 20)})])
        os.rename(path, os.path.join(os.path.dirname(path), "events.jsonl.bak"))
        self.assertIsNone(self.scan())


# The per-call rows of the Copilot CLI 1.0.87 store in tests/fixtures/
# copilot-store, summed with SQL over the unreduced store and without the
# reader: five calls, one of them after a resume, all on one day.
STORE_RECORDED = {"2026-09-21": {"turns": 5, "models": {
    "gpt-5.6-luna": {"input": 15, "output": 248, "cache_read": 47_632, "cache_write": 12_503}}}}
STORE_SESSION = "20fdee16-9f7d-40df-8c24-65473aa11a9b"
# The last release before assistant_usage_events, and the first with it:
# each run once against a fresh COPILOT_HOME on 2026-09-21, with 1.0.68
# writing schema_version 5 and no table, 1.0.69 schema_version 6 and a row.
PRE_TABLE, FIRST_WITH_TABLE = "1.0.68", "1.0.69"


class TestStoreRecording(unittest.TestCase):
    """A real session-store.db beside the events.jsonl of the same session,
    installed where Copilot writes them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "agent-sample")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".copilot")
        agent_logs.install("copilot-store", self.home, self.repo, database=copilot.STORE)

    def scan(self):
        return copilot.scan(self.repo, copilot.default_homes({"COPILOT_HOME": self.home}))

    def test_every_recorded_call(self):
        result = self.scan()
        self.assertEqual(result.days, STORE_RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_the_rows_and_the_snapshots_agree_on_the_session(self):
        # The same session read from its shutdown snapshots alone: the
        # fallback must reach the same totals, or choosing between the two
        # would change a figure rather than only its days.
        os.remove(os.path.join(self.home, copilot.STORE))
        self.assertEqual(self.scan().days, STORE_RECORDED)

    def test_the_rows_alone_still_find_their_repository(self):
        # With the session's log gone, the store's own working directory is
        # what ties its rows to the repository.
        shutil.rmtree(os.path.join(self.home, "session-state", STORE_SESSION))
        self.assertEqual(self.scan().days, STORE_RECORDED)


def call(n, session="s1", model="m", input=0, output=0, cache_read=0, cache_write=0,
         at="2026-08-05T10:00:00.000Z", details=True):
    """One row of assistant_usage_events: input_tokens contains both cache
    buckets, as Copilot writes it."""
    row = {"id": n, "session_id": session, "turn_index": 0, "model": model,
           "input_tokens": input + cache_read + cache_write, "output_tokens": output,
           "cache_read_tokens": cache_read, "cache_write_tokens": cache_write,
           "reasoning_tokens": 0, "created_at": at, "token_details_json": None}
    if details:
        row["token_details_json"] = [{"tokenType": "input", "tokenCount": input},
                                     {"tokenType": "cache_read", "tokenCount": cache_read},
                                     {"tokenType": "cache_write", "tokenCount": cache_write},
                                     {"tokenType": "output", "tokenCount": output}]
    return row


class TestStoreRules(LogHome):
    """session-store.db's per-call rows, and how they share a session with
    its shutdown snapshots."""

    def store(self, calls, sessions=None):
        tables = {"sessions": sessions if sessions is not None else
                  [{"id": "s1", "cwd": self.repo, "repository": None, "branch": "main",
                    "created_at": "2026-08-05T09:00:00.000Z"}]}
        if calls is not None:
            tables["assistant_usage_events"] = calls
        agent_logs.build_database(os.path.join(self.home, copilot.STORE), tables)

    def test_each_call_is_dated_by_its_own_time(self):
        # The shutdown reports both calls on the day it ran; the rows put
        # each call on its own day, which is what the table is for.
        self.write([start(self.repo), shutdown({"m": metric(300, 30, requests=2)},
                                               "2026-08-06T00:30:00.000Z")])
        self.store([call(1, input=100, output=10, at="2026-08-05T23:50:00.000Z"),
                    call(2, input=200, output=20, at="2026-08-06T00:10:00.000Z")])
        days = self.scan().days
        self.assertEqual({d: (v["turns"], v["models"]["m"]) for d, v in days.items()},
                         {"2026-08-05": (1, counts(100, 10)), "2026-08-06": (1, counts(200, 20))})

    def test_a_session_in_both_is_counted_once(self):
        # The shutdown runs the day after the calls, so the days say which
        # source was read: counted from the rows, as a tie is, and not also
        # from the snapshot.
        self.write([start(self.repo), shutdown({"m": metric(300, 30, cache_read=50, requests=2)},
                                               "2026-08-06T09:00:00.000Z")])
        self.store([call(1, input=100, output=10, cache_read=50),
                    call(2, input=200, output=20)])
        days = self.scan().days
        self.assertEqual({d: (v["turns"], v["models"]["m"]) for d, v in days.items()},
                         {"2026-08-05": (2, counts(300, 30, cache_read=50))})

    def test_a_snapshot_that_holds_more_than_the_rows_wins(self):
        # A session begun before the table existed and resumed after it: the
        # rows hold only the later calls, the snapshot the whole session.
        self.write([start(self.repo, version=PRE_TABLE), shutdown({"m": metric(900, 90, requests=3)})])
        self.store([call(1, input=300, output=30)])
        day = self.day()
        self.assertEqual((day["turns"], day["models"]["m"]), (3, counts(900, 90)))

    def test_rows_that_hold_more_than_the_snapshots_win(self):
        # A session that ended without a shutdown -- killed, or still open --
        # has rows past its last snapshot.
        self.write([start(self.repo), shutdown({"m": metric(100, 10)})])
        self.store([call(1, input=100, output=10), call(2, input=200, output=20)])
        day = self.day()
        self.assertEqual((day["turns"], day["models"]["m"]), (2, counts(300, 30)))

    def test_rows_with_no_log_at_all_are_counted(self):
        self.store([call(1, input=100, output=10)])
        self.assertEqual(self.day()["models"]["m"], counts(100, 10))

    def test_rows_with_no_log_from_another_directory_are_not(self):
        self.store([call(1, input=100, output=10)],
                   sessions=[{"id": "s1", "cwd": os.path.join(self.root, "other")}])
        self.assertIsNone(self.scan())

    def test_rows_with_no_log_and_no_session_row_are_not(self):
        # Nothing then says where the session ran: the store describes other
        # sessions, but not this one.
        self.store([call(1, input=100, output=10)], sessions=[{"id": "other", "cwd": self.repo}])
        self.assertIsNone(self.scan())

    def test_a_log_s_context_decides_over_the_store_s_directory(self):
        # The log records the remote and the commit, so where it says the
        # session ran elsewhere, a store row naming this directory does not
        # overrule it.
        self.write([start(os.path.join(self.root, "other")), shutdown({"m": metric(100, 10)})])
        self.store([call(1, input=100, output=10)])
        self.assertIsNone(self.scan())

    def test_a_store_without_the_usage_table_is_read_as_before(self):
        # Releases before the table: the store exists and holds none of it.
        self.write([start(self.repo, version=PRE_TABLE), shutdown({"m": metric(100, 10)})])
        self.store(None)
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.skipped), (counts(100, 10), 0))

    def test_a_damaged_store_is_counted_and_the_logs_still_read(self):
        # A session from before the table; one from after it is held back
        # instead (TestStableDays).
        self.write([start(self.repo, version=PRE_TABLE), shutdown({"m": metric(100, 10)})])
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, copilot.STORE), "w", encoding="utf-8") as f:
            f.write("not a database")
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.skipped), (counts(100, 10), 1))

    def test_a_row_whose_own_uncached_input_disagrees_is_counted_not_archived(self):
        bad = call(2, input=200, output=20)
        bad["token_details_json"][0]["tokenCount"] = 7
        self.store([call(1, input=100, output=10), bad])
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed), (counts(100, 10), 1))

    def test_a_row_with_no_details_is_taken_as_it_stands(self):
        self.store([call(1, input=100, output=10, cache_read=5, details=False)])
        self.assertEqual(self.day()["models"]["m"], counts(100, 10, cache_read=5))

    def test_sqlite_s_own_timestamp_form_is_read(self):
        # created_at defaults to datetime('now'), which has no T and no Z.
        self.store([call(1, input=100, output=10, at="2026-08-05 10:00:00")])
        self.assertEqual(self.day()["models"]["m"], counts(100, 10))

    def test_a_row_with_no_day_is_counted(self):
        self.store([call(1, input=100, output=10, at=None), call(2, input=200, output=20)])
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed), (counts(200, 20), 1))

    def test_two_copies_of_one_store_count_each_call_once(self):
        # A backed-up Copilot directory beside the live one: two files, the
        # same rows. A row keeps its id in the copy, so it is counted once,
        # as a copied log's snapshots are.
        self.store([call(1, input=100, output=10)])
        backup = os.path.join(self.root, "backup", ".copilot")
        shutil.copytree(self.home, backup)
        result = copilot.scan(self.repo, copilot.default_homes({"COPILOT_HOME": self.home})
                              + copilot.default_homes({"COPILOT_HOME": backup}))
        day = result.days["2026-08-05"]
        self.assertEqual((day["turns"], day["models"]["m"]), (1, counts(100, 10)))

    def test_unnamed_sessions_in_one_log_meet_their_rows_together(self):
        # A log whose starts name no session is keyed by its directory, and
        # a second unnamed start by an ordinal after it. The store keys the
        # same calls by the directory alone, so the rows must be weighed
        # against both parts of the log -- weighed against the first alone,
        # they win, and the second part is then counted again on its own.
        # From before the table, so the larger total decides, which is where
        # weighing one part alone would go wrong.
        unnamed = start(self.repo, version=PRE_TABLE)
        del unnamed["data"]["sessionId"]
        self.write([unnamed, shutdown({"m": metric(40, 0)}, "2026-08-05T12:00:00.000Z"),
                    unnamed, shutdown({"m": metric(100, 0)}, "2026-08-05T13:00:00.000Z")])
        self.store([call(1, input=100)])
        self.assertEqual(self.day()["models"]["m"], counts(140, 0))

    def test_a_store_reached_from_two_homes_is_read_once(self):
        # Once through the Copilot directory, once through a link to it: two
        # paths, one file. Read twice, every call would be counted twice.
        self.store([call(1, input=100, output=10)])
        state = os.path.join(self.home, "session-state")
        os.makedirs(state, exist_ok=True)
        alias = os.path.join(self.root, "alias")
        os.symlink(self.home, alias)
        homes = [state, self.home, os.path.join(alias, "session-state")]
        self.assertEqual(len(copilot.stores(homes)), 1)
        result = copilot.scan(self.repo, homes)
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed),
                         (counts(100, 10), 0))


class TestStableDays(LogHome):
    """A session from a release that writes per-call rows is dated by them,
    and never falls back to its shutdown days once a store is there: the
    archive keeps the larger record per day, so a session that moved from
    its calls' days to its shutdown's would be counted on both. Where its
    rows cannot be had, it is held back and the archive keeps what it has."""

    def store(self, calls):
        tables = {"sessions": [{"id": "s1", "cwd": self.repo, "branch": "main"}]}
        if calls:
            tables["assistant_usage_events"] = calls
        agent_logs.build_database(os.path.join(self.home, copilot.STORE), tables)

    def test_its_rows_are_read_even_where_the_snapshots_hold_more(self):
        # Rows pruned from the front of a session: the snapshot still holds
        # them all, and reading it would put them on the shutdown's day.
        self.write([start(self.repo, version=FIRST_WITH_TABLE),
                    shutdown({"m": metric(900, 90, requests=3)}, "2026-08-06T09:00:00.000Z")])
        self.store([call(3, input=300, output=30)])
        days = self.scan().days
        self.assertEqual({d: (v["turns"], v["models"]["m"]) for d, v in days.items()},
                         {"2026-08-05": (1, counts(300, 30))})

    def test_a_session_whose_rows_are_gone_is_held_back(self):
        self.write([start(self.repo, version="1.0.87"), shutdown({"m": metric(100, 10)})])
        self.store([call(1, session="another", input=5)])
        result = self.scan()
        self.assertEqual((result.days, result.held, result.malformed), ({}, 1, 0))

    def test_a_session_that_called_no_model_is_not_held_back(self):
        # It has no rows because it made no calls, not because they are gone,
        # and holding it would repeat the note on every run for nothing.
        self.write([start(self.repo, version="1.0.87"),
                    {"type": "session.shutdown", "timestamp": "2026-08-05T12:00:00.000Z",
                     "data": {"shutdownType": "routine", "modelMetrics": {}}}])
        self.store([call(1, session="another", input=5)])
        result = self.scan()
        self.assertEqual((result.days, result.held), ({}, 0))

    def test_an_unreadable_store_holds_back_every_such_session(self):
        self.write([start(self.repo, version="1.0.87"), shutdown({"m": metric(100, 10)})])
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, copilot.STORE), "w", encoding="utf-8") as f:
            f.write("not a database")
        result = self.scan()
        self.assertEqual((result.days, result.held, result.skipped), ({}, 1, 1))

    def test_with_no_store_at_all_the_snapshots_are_read(self):
        # The public recordings are logs alone, and so is a log tree copied
        # without its store: nothing then says the rows ever existed.
        self.write([start(self.repo, version="1.0.87"), shutdown({"m": metric(100, 10)})])
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.held), (counts(100, 10), 0))

    def test_a_session_from_before_the_table_keeps_the_larger_total(self):
        self.write([start(self.repo, version=PRE_TABLE), shutdown({"m": metric(900, 90, requests=3)})])
        self.store([call(1, input=300, output=30)])
        self.assertEqual(self.day()["models"]["m"], counts(900, 90))

    def test_a_session_that_names_no_release_keeps_the_larger_total(self):
        unversioned = start(self.repo)
        del unversioned["data"]["copilotVersion"]
        self.write([unversioned, shutdown({"m": metric(900, 90, requests=3)})])
        self.store([call(1, input=300, output=30)])
        self.assertEqual(self.day()["models"]["m"], counts(900, 90))

    def test_a_prerelease_of_the_first_release_with_the_table_counts_as_it(self):
        self.write([start(self.repo, version=FIRST_WITH_TABLE + "-2"),
                    shutdown({"m": metric(900, 90, requests=3)})])
        self.store([call(1, input=300, output=30)])
        self.assertEqual(self.day()["models"]["m"], counts(300, 30))

    def test_the_first_part_of_an_unnamed_log_names_the_release(self):
        # A log begun before the table and carried on after it: the rows
        # cannot hold the first part's calls, so the larger total decides,
        # as it does for any session begun before the table.
        before, after = start(self.repo, version=PRE_TABLE), start(self.repo, version=FIRST_WITH_TABLE)
        for unnamed in (before, after):
            del unnamed["data"]["sessionId"]
        self.write([before, shutdown({"m": metric(40, 0)}, "2026-08-05T12:00:00.000Z"),
                    after, shutdown({"m": metric(100, 0)}, "2026-08-05T13:00:00.000Z")])
        self.store([call(1, input=100)])
        self.assertEqual(self.day()["models"]["m"], counts(140, 0))

    def test_an_unnamed_log_from_a_release_with_the_table_is_read_from_its_rows(self):
        unnamed = start(self.repo, version=FIRST_WITH_TABLE)
        del unnamed["data"]["sessionId"]
        self.write([unnamed, shutdown({"m": metric(40, 0)}, "2026-08-05T12:00:00.000Z"),
                    unnamed, shutdown({"m": metric(100, 0)}, "2026-08-05T13:00:00.000Z")])
        self.store([call(1, input=100)])
        self.assertEqual(self.day()["models"]["m"], counts(100, 0))


if __name__ == "__main__":
    unittest.main()
