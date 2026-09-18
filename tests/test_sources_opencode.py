"""The OpenCode reader's arithmetic and its store readers.

The counter cases are the records OpenCode's five counter eras write. Each
expected total is worked out here from what the provider reported, not from
the reader's own rules: a call of 1,000 prompt tokens, 200 of them served
from cache, is 800 uncached input and 200 cache_read whatever the era stored.
"""

import datetime
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest

from clocwork import tokens
from clocwork.sources import opencode as oc
from tests import agent_logs

# An id minted at a known millisecond, in OpenCode's scheme: a prefix, then
# 12 hex digits of (time_ms << 12 | counter), then random characters.
def make_id(prefix, time_ms, counter=1, tail="abcdefgh"):
    raw = ((time_ms & ((1 << 36) - 1)) << 12) | counter
    return f"{prefix}_{raw:012x}{tail}"


# 2026-03-05T12:00:00Z, inside the era B recordings' window.
WHEN = 1772712000000


class TestVersions(unittest.TestCase):
    def test_numeric_comparison(self):
        self.assertEqual(oc.version_of("1.14.34"), (1, 14, 34))
        # The tags jump from v1.4 to v1.14, which text comparison gets wrong.
        self.assertLess(oc.version_of("1.4.9"), oc.version_of("1.14.0"))
        self.assertEqual(oc.version_of("v1.3.6-beta.2"), (1, 3, 6))

    def test_no_version(self):
        for value in (None, "", "dev", 17, {}):
            with self.subTest(value=value):
                self.assertEqual(oc.version_of(value), ())


class TestIds(unittest.TestCase):
    def test_a_real_id_explains_its_own_time(self):
        self.assertFalse(oc.fork_copy(make_id("msg", WHEN), WHEN))
        # Real ids drift a few milliseconds from the time the message records.
        self.assertFalse(oc.fork_copy(make_id("msg", WHEN - 7), WHEN))

    def test_a_copy_minted_later_is_a_fork(self):
        self.assertTrue(oc.fork_copy(make_id("msg", WHEN + 86_400_000), WHEN))
        self.assertTrue(oc.fork_copy(make_id("msg", WHEN + 61_000), WHEN))
        # Just inside the slack, so kept.
        self.assertFalse(oc.fork_copy(make_id("msg", WHEN + 59_000), WHEN))

    def test_a_descending_id_is_not_mistaken_for_a_copy(self):
        raw = ((WHEN & ((1 << 36) - 1)) << 12) | 1
        descending = f"msg_{(1 << 48) - 1 - raw:012x}zz"
        self.assertFalse(oc.fork_copy(descending, WHEN))

    def test_an_id_of_another_scheme_is_never_a_copy(self):
        for value in ("", None, "msg-not-hex", "0123456789ab"):
            with self.subTest(value=value):
                self.assertFalse(oc.fork_copy(value, WHEN))


class TestCounters(unittest.TestCase):
    def counters(self, t, provider="openai", model="gpt-5.3-codex", version="1.2.15"):
        return oc.counters(t, provider, model, oc.version_of(version))

    def test_era_b_openai_reasoning_inside_output(self):
        # A recorded v1.2.17 record (kimaki): 50,769 = 2,188 + 69 + 48,512,
        # so the 24 reasoning tokens are already inside the output. v1.2.x
        # stored an uncached input for OpenAI, so nothing comes off it.
        t = {"total": 50_769, "input": 2_188, "output": 69, "reasoning": 24,
             "cache": {"read": 48_512, "write": 0}}
        self.assertEqual(self.counters(t),
                         {"input": 2_188, "output": 69, "cache_read": 48_512, "cache_write": 0})

    def test_era_b_google_reasoning_outside_output(self):
        # A recorded v1.2.15 record (kimaki): 39,176 = 39,043 + 28 + 105, so
        # the reasoning is beside the output, as the v5 Google mapping
        # reported thoughts. Its provider id is the recorder's own, which is
        # why the model id has to be able to decide this by itself.
        t = {"total": 39_176, "input": 39_043, "output": 28, "reasoning": 105,
             "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.counters(t, provider="cached-google-real-events", model="gemini-2.5-flash"),
                         {"input": 39_043, "output": 133, "cache_read": 0, "cache_write": 0})

    def test_era_e_reasoning_outside_output(self):
        # A recorded v1.14.50 step (Irrlicht): 21,781 = 21,600 + 5 + 176.
        # From v1.3.16 OpenCode subtracts reasoning from output itself.
        t = {"total": 21_781, "input": 21_600, "output": 5, "reasoning": 176,
             "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.counters(t, model="qwen/qwen3-4b", version="1.14.50"),
                         {"input": 21_600, "output": 181, "cache_read": 0, "cache_write": 0})

    def test_era_d_reasoning_inside_output(self):
        # Recorded v1.3.13 records (opencode.el), the last window before
        # v1.3.16: 56,644 = 56,075 + 569 and 59,015 = 6,066 + 197 + 52,752,
        # so the 442 and 140 reasoning tokens are already inside the output.
        t = {"total": 56_644, "input": 56_075, "output": 569, "reasoning": 442,
             "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.counters(t, provider="Gemini", model="gemini-3.1-pro-preview-new", version="1.3.13"),
                         {"input": 56_075, "output": 569, "cache_read": 0, "cache_write": 0})
        t = {"total": 59_015, "input": 6_066, "output": 197, "reasoning": 140,
             "cache": {"read": 52_752, "write": 0}}
        self.assertEqual(self.counters(t, provider="Gemini", model="gemini-3.1-pro-preview-new", version="1.3.13"),
                         {"input": 6_066, "output": 197, "cache_read": 52_752, "cache_write": 0})

    def test_a_recorded_cache_write(self):
        # Recorded v1.17.20 Anthropic records (tmux-pane-dash), the first
        # with a cache write: 51,296 = 2 + 56 + 48,860 + 2,378, and a first
        # turn that writes the whole prompt, 51,273 = 2 + 33 + 51,238.
        t = {"total": 51_296, "input": 2, "output": 56, "reasoning": 0,
             "cache": {"write": 2_378, "read": 48_860}}
        self.assertEqual(self.counters(t, provider="anthropic", model="claude-fable-5", version="1.17.20"),
                         {"input": 2, "output": 56, "cache_read": 48_860, "cache_write": 2_378})
        t = {"total": 51_273, "input": 2, "output": 33, "reasoning": 0,
             "cache": {"write": 51_238, "read": 0}}
        self.assertEqual(self.counters(t, provider="anthropic", model="claude-fable-5", version="1.17.20"),
                         {"input": 2, "output": 33, "cache_read": 0, "cache_write": 51_238})

    def test_era_e_openai_reasoning_outside_output(self):
        # A recorded v1.17.20 OpenAI record (tmux-pane-dash): 27,959 =
        # 27,919 + 18 + 22, so the reasoning is beside the output - the
        # reverse of kimaki's v1.2.17 OpenAI records, which is why the
        # record's own total decides and neither the provider nor the release.
        t = {"total": 27_959, "input": 27_919, "output": 18, "reasoning": 22,
             "cache": {"write": 0, "read": 0}}
        self.assertEqual(self.counters(t, model="gpt-5.6-terra", version="1.17.20"),
                         {"input": 27_919, "output": 40, "cache_read": 0, "cache_write": 0})

    def test_a_total_that_fits_neither_reading_falls_back_to_the_version(self):
        t = {"input": 100, "output": 10, "reasoning": 4, "cache": {"read": 0, "write": 0}, "total": 999}
        self.assertEqual(self.counters(t, version="1.14.50")["output"], 14)
        self.assertEqual(self.counters(t, version="1.2.15")["output"], 10)

    def test_no_total_uses_the_version_and_the_provider(self):
        t = {"input": 100, "output": 10, "reasoning": 4, "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.counters(t, version="1.2.15")["output"], 10)
        self.assertEqual(self.counters(t, provider="google", model="gemini-2.5-pro",
                                       version="1.2.15")["output"], 14)
        self.assertEqual(self.counters(t, version="1.16.0")["output"], 14)

    def test_era_c_anthropic_input_includes_the_cache(self):
        # v1.3.4 and v1.3.5 only: the v6 SDK began including cache in
        # inputTokens while OpenCode still skipped subtracting it for
        # Anthropic. 5,000 reported input is 1,000 uncached.
        t = {"input": 5_000, "output": 50, "reasoning": 0, "cache": {"read": 3_000, "write": 1_000}}
        self.assertEqual(self.counters(t, provider="anthropic", model="claude-sonnet-4.5",
                                       version="1.3.4"),
                         {"input": 1_000, "output": 50, "cache_read": 3_000, "cache_write": 1_000})
        # The release after the fix stores it uncached, so nothing is taken off.
        self.assertEqual(self.counters(t, provider="anthropic", model="claude-sonnet-4.5",
                                       version="1.3.6")["input"], 5_000)
        # And in era C a non-Anthropic provider was already uncached.
        self.assertEqual(self.counters(t, version="1.3.4")["input"], 5_000)

    def test_era_a_input_includes_cache_reads_except_for_anthropic(self):
        t = {"input": 5_000, "output": 50, "reasoning": 0, "cache": {"read": 3_000, "write": 0}}
        self.assertEqual(self.counters(t, version="1.0.0")["input"], 2_000)
        self.assertEqual(self.counters(t, provider="anthropic", model="claude-3-7-sonnet",
                                       version="1.0.0")["input"], 5_000)

    def test_an_input_smaller_than_the_cache_read_is_left_alone(self):
        # It cannot be inclusive, whatever the era says, and subtracting would
        # throw the uncached prompt away.
        t = {"input": 40, "output": 5, "reasoning": 0, "cache": {"read": 3_000, "write": 0}}
        self.assertEqual(self.counters(t, version="1.0.0"),
                         {"input": 40, "output": 5, "cache_read": 3_000, "cache_write": 0})

    def test_a_record_with_no_version_but_a_total_is_not_read_as_the_oldest(self):
        # A `total` means the record was written by v1.1.57 or later, whose
        # input is already uncached, so nothing may come off it. Only a
        # record with neither a version nor a total can predate v1.0.62.
        has_total = {"input": 5_000, "output": 50, "reasoning": 0, "total": 8_000,
                     "cache": {"read": 3_000, "write": 0}}
        self.assertEqual(self.counters(has_total, version=None)["input"], 5_000)
        neither = {k: v for k, v in has_total.items() if k != "total"}
        self.assertEqual(self.counters(neither, version=None)["input"], 2_000)

    def test_a_gateway_prefixed_model_is_read_by_its_own_name(self):
        # An OpenRouter id names the gateway first; what the API behaves like
        # is the last part, and era C's inclusive input hangs on it.
        t = {"input": 5_000, "output": 50, "reasoning": 0, "cache": {"read": 3_000, "write": 1_000}}
        for model in ("claude-sonnet-4.5", "anthropic/claude-sonnet-4.5",
                      "openrouter/anthropic/claude-sonnet-4.5"):
            with self.subTest(model=model):
                self.assertEqual(self.counters(t, provider="openrouter", model=model,
                                               version="1.3.4")["input"], 1_000)
        # And the same for the Google reading of reasoning before v1.3.16.
        g = {"input": 100, "output": 10, "reasoning": 4, "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.counters(g, provider="openrouter", model="google/gemini-2.5-pro",
                                       version="1.2.15")["output"], 14)

    def test_counts_of_the_wrong_type_are_missing_rather_than_guessed(self):
        t = {"input": "4200", "output": 1.5, "reasoning": None, "cache": "none", "total": True}
        self.assertEqual(self.counters(t), tokens.empty_counts())

    def test_reasoning_is_counted_once_under_either_reading(self):
        # The archive's contract: the four counters are disjoint. The same
        # call, recorded by a release that folded reasoning into output and by
        # one that did not, differs by exactly the reasoning tokens and never
        # counts them twice.
        call = {"input": 1_000, "output": 200, "reasoning": 50, "cache": {"read": 300, "write": 20}}
        inside = self.counters({**call, "total": 1_520})    # total == input + output + cache
        outside = self.counters({**call, "total": 1_570})   # total == that + reasoning
        self.assertEqual(inside, {"input": 1_000, "output": 200, "cache_read": 300, "cache_write": 20})
        self.assertEqual(sum(inside.values()), 1_520)
        self.assertEqual(sum(outside.values()), 1_570)
        self.assertEqual(outside["output"] - inside["output"], 50)



def utc_day(ms):
    """The date a timestamp in milliseconds falls on, worked out here rather
    than with the reader's own helper."""
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


def make_repo(directory, remote=agent_logs.REMOTE):
    """A repository with one commit and an origin, as OpenCode would see it."""
    os.makedirs(directory, exist_ok=True)
    git(directory, "init", "-q")
    git(directory, "config", "user.email", "fixture@example.com")
    git(directory, "config", "user.name", "Fixture")
    if remote:
        git(directory, "remote", "add", "origin", remote)
    with open(os.path.join(directory, "a.py"), "w") as f:
        f.write("x = 1\n")
    git(directory, "add", "-A")
    git(directory, "commit", "-qm", "one")
    return directory


class TestFixtureStores(unittest.TestCase):
    """The committed fixtures, installed as OpenCode's data directory.

    Each expected figure is worked out from the record it comes from, in the
    comment beside it, never from the reader's own output.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(os.path.join(cls.tmp.name, "repo"))
        cls.home = os.path.join(cls.tmp.name, "home")
        agent_logs.install("opencode", cls.home, cls.repo)
        cls.result = oc.scan(cls.repo, [cls.home])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def models(self, date):
        return self.result.days.get(date, {}).get("models", {})

    def test_nothing_was_unreadable(self):
        self.assertEqual(self.result.skipped, 0)

    def test_the_recorded_gemini_day(self):
        # Two recorded v1.2.15 records (kimaki), reasoning beside the output:
        # inputs 39,043 + 39,366; outputs (28 + 105) + (6 + 0).
        self.assertEqual(self.models("2026-03-04"),
                         {"cached-google-real-events/gemini-2.5-flash":
                          {"input": 78_409, "output": 139, "cache_read": 0, "cache_write": 0}})
        self.assertEqual(self.result.days["2026-03-04"]["turns"], 2)

    def test_the_recorded_openai_day(self):
        # Two recorded v1.2.20 records, reasoning already inside the output:
        # inputs 45,922 + 1,217; outputs 815 + 278; cache reads 0 + 45,824.
        self.assertEqual(self.models("2026-03-06"),
                         {"openai/gpt-5.3-codex":
                          {"input": 47_139, "output": 1_093, "cache_read": 45_824, "cache_write": 0}})

    def test_the_recorded_era_e_days(self):
        # Irrlicht's scenarios, v1.14.50: 21,781 = 21,600 + 5 + 176, so the
        # reasoning is added to the output; and 19,644 = 19,642 + 2 with none.
        self.assertEqual(self.models("2026-05-29"),
                         {"qwen/qwen3-4b": {"input": 21_600, "output": 181, "cache_read": 0, "cache_write": 0}})
        self.assertEqual(self.models("2026-05-22"),
                         {"Qwen/Qwen3-Coder-Next": {"input": 19_642, "output": 2, "cache_read": 0, "cache_write": 0}})

    def test_the_recorded_cache_write_day(self):
        # Three recorded v1.17.20 records (tmux-pane-dash). Anthropic: inputs
        # 2 + 2; outputs 33 + 56; cache reads 0 + 48,860; cache writes
        # 51,238 + 2,378. OpenAI: 27,919 input, 18 output + 22 reasoning.
        self.assertEqual(self.models("2026-07-17"),
                         {"anthropic/claude-fable-5":
                          {"input": 4, "output": 89, "cache_read": 48_860, "cache_write": 53_616},
                          "openai/gpt-5.6-terra":
                          {"input": 27_919, "output": 40, "cache_read": 0, "cache_write": 0}})
        self.assertEqual(self.result.days["2026-07-17"]["turns"], 3)

    def test_the_recorded_era_d_day(self):
        # Two recorded v1.3.13 records (opencode.el), reasoning inside the
        # output: inputs 56,075 + 6,066; outputs 569 + 197; cache reads
        # 0 + 52,752. The day also holds the hand-written empty-directory
        # session, so the recording is read by its own model.
        self.assertEqual(self.models("2026-04-03")["Gemini/gemini-3.1-pro-preview-new"],
                         {"input": 62_141, "output": 766, "cache_read": 52_752, "cache_write": 0})

    def test_a_record_whose_stream_names_no_model(self):
        # codor's v1.17.14 stream carries ids and counts but no model, so the
        # archive says unknown rather than guessing: 10,134 = 10,119 + 3 + 12.
        self.assertEqual(self.models("2026-07-10"),
                         {"unknown": {"input": 10_119, "output": 15, "cache_read": 0, "cache_write": 0}})

    def test_records_with_no_tokens_at_all_add_no_turn(self):
        # The v1.17.9 rows (OpenAgents) are real, and every count in them is
        # zero. The dates they carry are read from the fixture, so this fails
        # if a later refresh brings in a record that does have usage.
        def all_zero(t):
            # A record that carries counts, all of them zero. A message with
            # no tokens at all is a different case: its step-finish part
            # holds the usage, as codor's recorded stream does.
            return isinstance(t, dict) and not any(
                list(t.get("cache", {}).values()) + [v for k, v in t.items() if k != "cache"])

        zero = [r for r in agent_logs.records("opencode", os.path.join("s1", "message.jsonl"))
                if r["data"].get("role") == "assistant" and all_zero(r["data"].get("tokens"))]
        self.assertTrue(zero, "the fixture no longer holds a record with no usage")
        for record in zero:
            date = utc_day(record["data"]["time"]["created"])
            with self.subTest(date=date):
                self.assertNotIn(date, self.result.days)
        self.assertNotIn("openagents/khala",
                         {m for day in self.result.days.values() for m in day["models"]})

    def test_a_forks_copy_is_not_counted_again(self):
        # The copy sits in a real session, carries 999,999 input and an id
        # minted a day after the message it copies.
        self.assertNotIn("2026-03-05", self.result.days)
        every = {v for day in self.result.days.values() for c in day["models"].values() for v in c.values()}
        self.assertNotIn(999_999, every)

    def test_a_record_the_migration_copied_is_counted_once(self):
        # The J1 files and the database both hold it, as a store that has
        # been migrated does. 1,200 input, 90 output, 20 reasoning inside.
        self.assertEqual(self.models("2026-02-01"),
                         {"openai/gpt-5.2-codex": {"input": 1_200, "output": 90, "cache_read": 0, "cache_write": 0}})
        self.assertEqual(self.result.days["2026-02-01"]["turns"], 1)

    def test_the_oldest_file_store_is_read(self):
        # J0 keeps no directory, so the session is placed by its message's
        # root, and v0.5.29 stored OpenAI's cache reads inside the input:
        # 2,500 - 1,500 = 1,000.
        self.assertEqual(self.models("2025-08-01"),
                         {"openai/gpt-4.1": {"input": 1_000, "output": 40, "cache_read": 1_500, "cache_write": 0}})

    def test_the_hand_written_era_days(self):
        # No public recording covers these, so the records are built from
        # getUsage as shipped: era A subtracts the cache read, era C the read
        # and the write, era D nothing.
        self.assertEqual(self.models("2026-01-05")["openai/gpt-4.1"]["input"], 2_000)
        self.assertEqual(self.models("2026-03-29")["anthropic/claude-sonnet-4.5"],
                         {"input": 1_000, "output": 50, "cache_read": 3_000, "cache_write": 1_000})
        self.assertEqual(self.models("2026-03-30")["anthropic/claude-sonnet-4.5"]["input"], 1_000)

    def test_a_session_only_the_v2_tables_hold(self):
        # 2,200 = 2,000 + 150 + 50, and v1.18.0 keeps reasoning out of output.
        self.assertEqual(self.models("2026-04-02"),
                         {"anthropic/claude-sonnet-5":
                          {"input": 2_000, "output": 200, "cache_read": 0, "cache_write": 0}})

    def test_a_session_with_an_empty_directory(self):
        self.assertEqual(self.models("2026-04-03")["openai/gpt-5.3-codex"]["input"], 300)

    def test_a_foreign_project_id_at_our_path_is_refused(self):
        # Another repository's 40-digit id, on a session whose directory is
        # ours: another history cloned to the same path, not our work.
        self.assertNotIn("2026-04-01", self.result.days)

    def test_every_day_belongs_to_a_session_of_this_repository(self):
        self.assertEqual(sorted(self.result.days), [
            "2025-08-01", "2026-01-05", "2026-02-01", "2026-03-04", "2026-03-06", "2026-03-29",
            "2026-03-30", "2026-04-02", "2026-04-03", "2026-05-22", "2026-05-29", "2026-07-10",
            "2026-07-17"])


AT = 1780000000000   # 2026-05-28T...Z, a plain weekday inside every era E release
PROJECT_ID = "d56552e46d00ecffe51919c7e8e32677db654334"   # the placeholder remote's id
USAGE = {"total": 1_100, "input": 1_000, "output": 100, "reasoning": 0, "cache": {"read": 0, "write": 0}}


def one_session_db(path, project, directory, version="1.14.50", root=None, usage=USAGE,
                   at=AT, tail="testcase01"):
    """A database holding one session and one assistant message with usage."""
    sid, mid = make_id("ses", at, 1, tail), make_id("msg", at, 1, tail)
    agent_logs.build_database(path, {
        "session": [{"id": sid, "project_id": project, "directory": directory, "version": version,
                     "parent_id": None, "path": "", "time_created": at}],
        "message": [{"id": mid, "session_id": sid, "time_created": at,
                     "data": {"role": "assistant", "modelID": "gpt-5.3-codex", "providerID": "openai",
                              "time": {"created": at}, "tokens": usage,
                              "path": {"cwd": root or directory, "root": root or directory}}}],
    })
    return sid


def scanned(repo, homes):
    """(days, skipped) from a scan, or (None, None) when it found nothing."""
    result = oc.scan(repo, homes)
    return (None, None) if result is None else (result.days, result.skipped)


class TestMatching(unittest.TestCase):
    """Which sessions count as the repository's work."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.db = os.path.join(self.home, "opencode.db")
        self.project = oc.known_ids(self.repo)

    def test_the_remote_hash_is_the_id_opencode_writes(self):
        # sha1("git-remote:github.com/example/agent-sample"), which OpenCode
        # builds from origin the same way paths.remote_key does.
        self.assertIn(PROJECT_ID, self.project)

    def test_a_session_of_the_same_remote_counts_wherever_it_ran(self):
        # Another clone's directory, which is not inside this repository.
        one_session_db(self.db, PROJECT_ID,
                       os.path.join(self.tmp.name, "some-other-clone"))
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_a_session_of_another_remote_in_another_directory_is_not_ours(self):
        one_session_db(self.db, "0f6c3c1ba2ee7d0f3e0b1a9c8d7e6f5a4b3c2d1e",
                       os.path.join(self.tmp.name, "elsewhere"))
        self.assertEqual(scanned(self.repo, [self.home]), (None, None))

    def test_a_root_commit_id_counts_when_the_session_ran_here(self):
        # Releases before v1.15.11 named the project by the first commit.
        root = subprocess.run(["git", "-C", self.repo, "rev-list", "--max-parents=0", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        one_session_db(self.db, root, self.repo, version="1.2.0")
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_the_id_cached_in_the_git_directory_counts(self):
        common = subprocess.run(["git", "-C", self.repo, "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
        with open(os.path.join(self.repo, common, "opencode"), "w") as f:
            f.write("cached-id-written-by-opencode\n")
        one_session_db(self.db, "cached-id-written-by-opencode",
                       os.path.join(self.tmp.name, "anywhere"))
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_a_directory_below_the_repository_counts(self):
        one_session_db(self.db, "global", os.path.join(self.repo, "src", "deep"))
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_a_directory_outside_the_repository_does_not(self):
        one_session_db(self.db, "global", os.path.join(self.tmp.name, "not-the-repo"))
        self.assertEqual(scanned(self.repo, [self.home]), (None, None))

    def test_a_repository_without_a_remote_still_matches_by_directory(self):
        bare = make_repo(os.path.join(self.tmp.name, "no-remote"), remote=None)
        one_session_db(self.db, "global", bare)
        days, _ = scanned(bare, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)


class TestTheV2Table(unittest.TestCase):
    """The experimental session_message table, which projects the V1 rows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)

    def v2_db(self, path, rows, v1=()):
        sid = make_id("ses", AT, 1, "v2case0001")
        agent_logs.build_database(path, {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "", "parent_id": None, "path": "", "time_created": AT}],
            "message": list(v1) or [{"id": make_id("msg", AT, 8, "v2case0001"),
                                     "session_id": sid, "time_created": AT,
                                     "data": {"role": "user", "time": {"created": AT}}}],
            "session_message": [{"id": mid, "session_id": sid, "type": "assistant", "seq": n + 1,
                                 "time_created": AT,
                                 "data": {"role": "assistant", "modelID": "claude-sonnet-5",
                                          "providerID": "anthropic", "time": {"created": created},
                                          "tokens": USAGE,
                                          "path": {"cwd": self.repo, "root": self.repo}}}
                                for n, (mid, created) in enumerate(rows)],
        })
        return sid

    def test_a_forks_copy_in_the_v2_table_is_not_counted_again(self):
        # The copy records the same time as the row it copies and carries an
        # id minted a day later, exactly as it does in the V1 tables.
        self.v2_db(os.path.join(self.home, "opencode.db"),
                   [(make_id("msg", AT, 1, "v2case0001"), AT),
                    (make_id("msg", AT + 86_400_000, 2, "v2forkcopy"), AT)])
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual([day["turns"] for day in days.values()], [1])

    def test_a_row_with_no_session_version_is_read_as_the_release_it_arrived_in(self):
        # session_message exists from v1.14.34, which is past v1.3.16, so the
        # reasoning is outside the output whatever the session row says - and
        # an Anthropic record would otherwise read it as inside.
        # No `total`, so the version is what decides; with one, the record
        # would settle the question itself and the floor would never run.
        usage = {"input": 1_000, "output": 100, "reasoning": 40,
                 "cache": {"read": 0, "write": 0}}
        sid = make_id("ses", AT, 1, "v2case0001")
        agent_logs.build_database(os.path.join(self.home, "opencode.db"), {
            # The session row names a release older than the table it holds,
            # which a migrated store can: the floor has to win over it, and a
            # session naming nothing would not tell the two apart.
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.2.0", "parent_id": None, "path": "", "time_created": AT}],
            "message": [{"id": make_id("msg", AT, 8, "v2case0001"), "session_id": sid,
                         "time_created": AT, "data": {"role": "user", "time": {"created": AT}}}],
            "session_message": [{"id": make_id("msg", AT, 1, "v2case0001"), "session_id": sid,
                                 "type": "assistant", "seq": 1, "time_created": AT,
                                 "data": {"role": "assistant", "modelID": "claude-sonnet-5",
                                          "providerID": "anthropic", "time": {"created": AT},
                                          "tokens": usage,
                                          "path": {"cwd": self.repo, "root": self.repo}}}],
        })
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(days[utc_day(AT)]["models"]["anthropic/claude-sonnet-5"],
                         {"input": 1_000, "output": 140, "cache_read": 0, "cache_write": 0})

    def test_v1_rows_in_one_database_and_v2_rows_in_another_are_one_call(self):
        # A channel switch can leave the V1 rows in one file and the V2
        # projection in the other. They carry different ids, so only the
        # exclusion keeps the call from being counted twice.
        sid = make_id("ses", AT, 1, "v2case0001")
        v1 = [{"id": make_id("msg", AT, 3, "v1rowhere0"), "session_id": sid, "time_created": AT,
               "data": {"role": "assistant", "modelID": "claude-sonnet-5", "providerID": "anthropic",
                        "time": {"created": AT}, "tokens": USAGE,
                        "path": {"cwd": self.repo, "root": self.repo}}}]
        agent_logs.build_database(os.path.join(self.home, "opencode.db"), {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.14.50", "parent_id": None, "path": "", "time_created": AT}],
            "message": v1,
        })
        self.v2_db(os.path.join(self.home, "opencode-beta.db"),
                   [(make_id("msg", AT, 1, "v2rowhere0"), AT)])
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual([day["turns"] for day in days.values()], [1])
        self.assertEqual(days[utc_day(AT)]["models"]["anthropic/claude-sonnet-5"]["input"], 1_000)


    def test_a_v1_record_with_no_usage_does_not_hide_the_v2_rows(self):
        # The v1.17.9 recordings hold assistant messages whose every count is
        # zero. One of those must not stand in for the session's V2 usage, or
        # the session is lost: 1,000 input and 100 output here.
        sid = make_id("ses", AT, 1, "v2case0001")
        zero = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        self.v2_db(os.path.join(self.home, "opencode.db"),
                   [(make_id("msg", AT, 1, "v2case0001"), AT)],
                   v1=[{"id": make_id("msg", AT, 7, "zerousage0"), "session_id": sid,
                        "time_created": AT,
                        "data": {"role": "assistant", "modelID": "khala", "providerID": "openagents",
                                 "time": {"created": AT}, "tokens": zero,
                                 "path": {"cwd": self.repo, "root": self.repo}}}])
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(days[utc_day(AT)]["models"]["anthropic/claude-sonnet-5"]["input"], 1_000)

    def test_a_database_of_only_the_v2_tables_is_read(self):
        # A channel database a V2-only release wrote has no message table at
        # all, which is a store rather than a damaged file.
        sid = make_id("ses", AT, 1, "v2case0001")
        agent_logs.build_database(os.path.join(self.home, "opencode.db"), {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.18.0", "parent_id": None, "path": "", "time_created": AT}],
            "session_message": [{"id": make_id("msg", AT, 1, "v2case0001"), "session_id": sid,
                                 "type": "assistant", "seq": 1, "time_created": AT,
                                 "data": {"role": "assistant", "modelID": "claude-sonnet-5",
                                          "providerID": "anthropic", "time": {"created": AT},
                                          "tokens": USAGE,
                                          "path": {"cwd": self.repo, "root": self.repo}}}],
        })
        days, skipped = scanned(self.repo, [self.home])
        self.assertEqual(skipped, 0)
        self.assertEqual(days[utc_day(AT)]["models"]["anthropic/claude-sonnet-5"]["input"], 1_000)


class TestDamagedAndDuplicated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)

    def test_a_row_whose_json_will_not_parse_is_counted(self):
        # Losing a row silently would leave the run saying it scanned
        # everything, so it is reported the way the other readers report a
        # line they cannot parse.
        sid = make_id("ses", AT, 1, "damaged001")
        path = os.path.join(self.home, "opencode.db")
        agent_logs.build_database(path, {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.14.50", "parent_id": None, "path": "", "time_created": AT}],
            "message": [{"id": make_id("msg", AT, 1, "damaged001"), "session_id": sid,
                         "time_created": AT, "data": None}],
        })
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE message SET data = ?", ('{"role": "assistant", "tok',))
        result = oc.scan(self.repo, [self.home])
        self.assertEqual((result.days, result.malformed, result.skipped), ({}, 1, 0))

    def test_a_message_read_with_and_without_its_parts_is_one_call(self):
        # A pruned part file in the older store, and the part in the newer
        # one: the same call under a message id and under a part id.
        sid = make_id("ses", AT, 1, "dupcase001")
        mid = make_id("msg", AT, 1, "dupcase001")
        j1 = os.path.join(self.home, "storage")
        for rel, doc in (
            (os.path.join("session", PROJECT_ID, sid + ".json"),
             {"id": sid, "projectID": PROJECT_ID, "directory": self.repo, "version": "1.1.13",
              "time": {"created": AT}}),
            (os.path.join("message", sid, mid + ".json"),
             {"id": mid, "sessionID": sid, "role": "assistant", "modelID": "gpt-5.3-codex",
              "providerID": "openai", "path": {"cwd": self.repo, "root": self.repo},
              "time": {"created": AT}, "tokens": USAGE}),
        ):
            os.makedirs(os.path.dirname(os.path.join(j1, rel)), exist_ok=True)
            with open(os.path.join(j1, rel), "w") as f:
                json.dump(doc, f)
        agent_logs.build_database(os.path.join(self.home, "opencode.db"), {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.1.13", "parent_id": None, "path": "", "time_created": AT}],
            "message": [{"id": mid, "session_id": sid, "time_created": AT,
                         "data": {"role": "assistant", "modelID": "gpt-5.3-codex",
                                  "providerID": "openai", "time": {"created": AT},
                                  "tokens": USAGE,
                                  "path": {"cwd": self.repo, "root": self.repo}}}],
            "part": [{"id": make_id("prt", AT, 1, "dupcase001"), "message_id": mid,
                      "session_id": sid, "time_created": AT,
                      "data": {"type": "step-finish", "tokens": USAGE}}],
        })
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual([day["turns"] for day in days.values()], [1])
        self.assertEqual(days[utc_day(AT)]["models"]["openai/gpt-5.3-codex"]["input"], 1_000)

    def test_every_step_of_a_message_is_counted(self):
        # A message's own tokens are overwritten by its latest step, so the
        # steps are what is summed: two parts of 1,000 are 2,000, not 1,000.
        sid, mid = make_id("ses", AT, 1, "steps00001"), make_id("msg", AT, 1, "steps00001")
        agent_logs.build_database(os.path.join(self.home, "opencode.db"), {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "1.14.50", "parent_id": None, "path": "", "time_created": AT}],
            "message": [{"id": mid, "session_id": sid, "time_created": AT,
                         "data": {"role": "assistant", "modelID": "gpt-5.3-codex",
                                  "providerID": "openai", "time": {"created": AT},
                                  "tokens": USAGE,
                                  "path": {"cwd": self.repo, "root": self.repo}}}],
            "part": [{"id": make_id("prt", AT, n, "steps00001"), "message_id": mid,
                      "session_id": sid, "time_created": AT,
                      "data": {"type": "step-finish", "tokens": USAGE}} for n in (1, 2)] +
                    # A part of another type carrying a tokens block must not
                    # be counted: only a step-finish is a model call.
                    [{"id": make_id("prt", AT, 3, "steps00001"), "message_id": mid,
                      "session_id": sid, "time_created": AT,
                      "data": {"type": "step-start", "tokens": USAGE}}],
        })
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(days[utc_day(AT)]["models"]["openai/gpt-5.3-codex"]["input"], 2_000)
        self.assertEqual(days[utc_day(AT)]["turns"], 2)


class TestHomes(unittest.TestCase):
    def test_the_data_directory_follows_xdg(self):
        self.assertEqual(oc.default_homes({"XDG_DATA_HOME": "/data"}), ["/data/opencode"])
        home = os.path.expanduser("~")
        self.assertEqual(oc.default_homes({}), [os.path.join(home, ".local", "share", "opencode")])

    def test_opencode_db_is_added_absolute_or_relative(self):
        self.assertEqual(oc.default_homes({"XDG_DATA_HOME": "/data", "OPENCODE_DB": "/tmp/other.db"}),
                         ["/data/opencode", "/tmp/other.db"])
        self.assertEqual(oc.default_homes({"XDG_DATA_HOME": "/data", "OPENCODE_DB": "beta.db"}),
                         ["/data/opencode", "/data/opencode/beta.db"])
        # An in-memory database holds nothing a later run could read.
        self.assertEqual(oc.default_homes({"XDG_DATA_HOME": "/data", "OPENCODE_DB": ":memory:"}),
                         ["/data/opencode"])

    def test_a_home_that_is_a_file_is_read_as_a_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            db = os.path.join(tmp, "elsewhere.db")
            one_session_db(db, PROJECT_ID, repo)
            days, _ = scanned(repo, [db])
            self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_every_channel_database_in_the_directory_is_read(self):
        # A channel switch leaves a second database beside the first. Each
        # gets a call of its own here, on a different day, so reading only
        # opencode.db would lose one; and both also hold one shared record,
        # which must still be counted once.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            shared = one_session_db(os.path.join(home, "opencode.db"), PROJECT_ID, repo)
            one_session_db(os.path.join(home, "opencode-beta.db"), PROJECT_ID, repo,
                           at=AT + 86_400_000, tail="betachann1")
            # The shared record, in the beta database too, under its own id.
            with sqlite3.connect(os.path.join(home, "opencode-beta.db")) as conn:
                for row in sqlite3.connect(os.path.join(home, "opencode.db")).execute(
                        "SELECT id, session_id, time_created, data FROM message"):
                    conn.execute("INSERT INTO message (id, session_id, time_created, data) "
                                 "VALUES (?, ?, ?, ?)", row)
                conn.execute("INSERT INTO session (id, project_id, directory, version, parent_id, "
                             "path, time_created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (shared, PROJECT_ID, repo, "1.14.50", None, "", AT))
            days, _ = scanned(repo, [home])
            self.assertEqual(sorted(days), [utc_day(AT), utc_day(AT + 86_400_000)])
            self.assertEqual([days[d]["turns"] for d in sorted(days)], [1, 1])

    def test_a_damaged_database_is_counted_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            with open(os.path.join(home, "opencode.db"), "w") as f:
                f.write("this is not a database\n")
            days, skipped = scanned(repo, [home])
            self.assertEqual((days, skipped), ({}, 1))

    def test_a_part_file_that_is_json_but_not_an_object_is_counted(self):
        # Valid JSON of the wrong shape must be counted as unreadable, not
        # raised: one damaged file cannot be allowed to stop a run.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            part = os.path.join(home, "storage", "part", "msg_x", "prt_x.json")
            os.makedirs(os.path.dirname(part))
            with open(part, "w") as f:
                f.write('"step-finish"\n')
            days, skipped = scanned(repo, [home])
            self.assertEqual((days, skipped), ({}, 1))

    def test_a_directory_with_no_store_is_no_logs_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            self.assertIsNone(oc.scan(repo, [os.path.join(tmp, "nothing-here")]))

if __name__ == "__main__":
    unittest.main()
