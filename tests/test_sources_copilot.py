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


def context(repo, **over):
    base = {"cwd": repo, "gitRoot": repo, "repository": "example/agent-sample",
            "repositoryHost": "github.com", "headCommit": "a" * 40, "baseCommit": "b" * 40}
    base.update(over)
    return base


def start(repo, sid="s1", ts="2026-08-05T10:00:00.000Z", **over):
    return {"type": "session.start", "timestamp": ts,
            "data": {"sessionId": sid, "copilotVersion": "1.0.78", "startTime": ts,
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


class TestRules(unittest.TestCase):
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

    def test_counters_that_go_backwards_are_counted_not_archived(self):
        self.write([start(self.repo),
                    shutdown({"m": metric(100, 20)}, "2026-08-05T12:00:00.000Z"),
                    shutdown({"m": metric(40, 8)}, "2026-08-05T13:00:00.000Z")])
        result = self.scan()
        self.assertEqual(result.days["2026-08-05"]["models"]["m"], counts(100, 20))
        self.assertEqual(result.malformed, 1)

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
        self.assertEqual(self.scan().days, {})

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

    def test_a_log_under_another_name_is_not_read(self):
        path = self.write([start(self.repo), shutdown({"m": metric(100, 20)})])
        os.rename(path, os.path.join(os.path.dirname(path), "events.jsonl.bak"))
        self.assertIsNone(self.scan())


if __name__ == "__main__":
    unittest.main()
