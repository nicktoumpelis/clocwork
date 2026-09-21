"""Kilo Code reads an OpenCode store, so this file tests only what a fork
changes: where the store is, what its databases are called, where the
project id is cached, and which counter era its records are read at.

The records themselves are OpenCode's, proven by Kilo's own
`20260510033149_session_usage` migration, which sums
`$.tokens.cache.read`/`write` out of the same `message.data` JSON. Their
arithmetic is tested against six real recordings in
tests/test_sources_opencode.py and is not repeated here.
"""

import json
import os
import subprocess
import tempfile
import unittest

from clocwork import tokens
from clocwork.sources import kilo
from clocwork.sources import opencode as oc
from tests import agent_logs
from tests.test_sources_opencode import AT, PROJECT_ID, USAGE, make_id, make_repo, one_session_db


def kilo_db(path, repo, version="7.7.6", usage=USAGE, at=AT, tail="kilocase01", project=PROJECT_ID):
    return one_session_db(path, project, repo, version=version, usage=usage, at=at, tail=tail)


def scanned(repo, homes):
    result = kilo.scan(repo, homes)
    return (None, None) if result is None else (result.days, result.skipped)


class TestHomes(unittest.TestCase):
    def test_the_data_directory_is_kilo_s_own(self):
        # global.ts: `const app = "kilo"`, and xdg-basedir ignores the
        # platform, so this is the path on macOS too.
        self.assertEqual(kilo.default_homes({"XDG_DATA_HOME": "/data"}), ["/data/kilo"])
        home = os.path.expanduser("~")
        self.assertEqual(kilo.default_homes({}), [os.path.join(home, ".local", "share", "kilo")])

    def test_kilo_db_is_added_absolute_or_relative(self):
        self.assertEqual(kilo.default_homes({"XDG_DATA_HOME": "/data", "KILO_DB": "/tmp/other.db"}),
                         ["/data/kilo", "/tmp/other.db"])
        self.assertEqual(kilo.default_homes({"XDG_DATA_HOME": "/data", "KILO_DB": "nightly.db"}),
                         ["/data/kilo", "/data/kilo/nightly.db"])
        # getPath() accepts `:memory:`, which holds nothing a later run reads.
        self.assertEqual(kilo.default_homes({"XDG_DATA_HOME": "/data", "KILO_DB": ":memory:"}),
                         ["/data/kilo"])

    def test_opencode_s_own_variables_are_not_read(self):
        self.assertEqual(kilo.default_homes({"XDG_DATA_HOME": "/data", "OPENCODE_DB": "/tmp/oc.db"}),
                         ["/data/kilo"])


class TestTheStoreDescriptor(unittest.TestCase):
    def test_kilo_reads_its_own_databases_and_the_name_it_renamed(self):
        # db.ts getChannelPath(): a release channel writes kilo.db, another
        # channel kilo-<channel>.db, and an opencode-<channel>.db left by the
        # rename is still read where the new name is absent.
        self.assertEqual(oc.KILO.databases, ("kilo*.db", "opencode-*.db"))

    def test_opencode_does_not_read_kilo_s_databases(self):
        self.assertEqual(oc.OPENCODE.databases, ("opencode*.db",))

    def test_kilo_caches_its_project_id_under_its_own_name(self):
        # project.ts reads path.join(commonDirectory, "kilo"), marked
        # kilocode_change where OpenCode reads "opencode".
        self.assertEqual((oc.KILO.cache_name, oc.OPENCODE.cache_name), ("kilo", "opencode"))

    def test_kilo_has_no_file_store_generations(self):
        # Its migrations begin long after OpenCode's v1.2.0 database, and its
        # data directory is its own, so no J0 or J1 store can sit in it.
        self.assertFalse(oc.KILO.file_stores)
        self.assertTrue(oc.OPENCODE.file_stores)

    def test_a_file_store_in_kilo_s_directory_is_not_read(self):
        # The behaviour the flag above buys: a storage/ tree in the kilo
        # directory belongs to something else, and reading it would file
        # another tool's usage under Kilo Code.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            root = os.path.join(home, "storage")
            for table, doc in (("session", {"id": "ses_j1", "projectID": PROJECT_ID,
                                            "directory": repo, "version": "1.1.60"}),
                               ("message", {"id": "msg_j1", "sessionID": "ses_j1",
                                            "role": "assistant", "providerID": "openai",
                                            "modelID": "gpt-5.3-codex", "time": {"created": AT},
                                            "tokens": USAGE})):
                d = os.path.join(root, table, "ses_j1")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, f"{doc['id']}.json"), "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            self.assertIsNone(kilo.scan(repo, [home]))
            # The same tree under OpenCode's descriptor is read, so the
            # store really is one this reader could have counted.
            self.assertIsNotNone(oc.scan(repo, [home]))

    def test_two_database_patterns_that_overlap_read_a_file_once(self):
        # `databases` is a list of globs, and a later one could be widened to
        # cover an earlier one (`kilo-*.db` beside `kilo*.db`). Usage read
        # twice is harmless, because a record carries the id it was read
        # under -- but a store that cannot be read at all is *counted*, and
        # counting one damaged file as two would be a figure the run reports.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            with open(os.path.join(home, "kilo-beta.db"), "w", encoding="utf-8") as f:
                f.write("not a database")
            overlapping = oc.KILO._replace(databases=("kilo*.db", "kilo-*.db"))
            self.assertEqual(oc.scan(repo, [home], overlapping).skipped, 1)

    def test_only_kilo_floors_the_era(self):
        self.assertEqual(oc.KILO.floor, oc.ERA_E)
        self.assertEqual(oc.OPENCODE.floor, ())


class TestTheEraFloor(unittest.TestCase):
    """Kilo forked after the last era boundary, so its records are read at
    the newest rules whatever version string they carry."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)

    def day(self, version, usage):
        kilo_db(os.path.join(self.home, "kilo.db"), self.repo, version=version, usage=usage)
        days, _ = scanned(self.repo, [self.home])
        return next(iter(days.values()))["models"]

    def test_a_source_build_records_the_word_local(self):
        # installation/version.ts: InstallationVersion is "local" when
        # KILO_VERSION is not defined at build time.
        self.assertEqual(oc.version_of("local"), ())

    def test_a_local_build_is_not_read_as_the_oldest_era(self):
        # Era A subtracted the cache read from the prompt for every provider
        # but Anthropic. Read that way, a 1,000-token prompt with 400 served
        # from cache reports 600 uncached; Kilo never wrote that shape, and
        # the floor is what stops an empty version reaching the rule.
        usage = {"input": 1_000, "output": 100, "reasoning": 0, "cache": {"read": 400, "write": 0}}
        models = self.day("local", usage)
        self.assertEqual(models["openai/gpt-5.3-codex"],
                         {"input": 1_000, "output": 100, "cache_read": 400, "cache_write": 0})

    def test_reasoning_sits_outside_the_output_without_a_total(self):
        # Before era E the provider decided, and this record's provider is
        # one whose reasoning was inside. At the floor it is outside, so the
        # output is 100 + 40.
        usage = {"input": 1_000, "output": 100, "reasoning": 40, "cache": {"read": 0, "write": 0}}
        models = self.day("local", usage)
        self.assertEqual(models["openai/gpt-5.3-codex"]["output"], 140)

    def test_a_record_that_carries_a_total_is_still_believed_over_the_floor(self):
        # The floor is a default, not a rule: a total is evidence, and here
        # it says the reasoning is already inside the output.
        usage = {"total": 1_140, "input": 1_000, "output": 140, "reasoning": 40,
                 "cache": {"read": 0, "write": 0}}
        models = self.day("7.7.6", usage)
        self.assertEqual(models["openai/gpt-5.3-codex"]["output"], 140)

    def test_opencode_still_reads_its_own_oldest_era(self):
        # The floor must not leak into the other source: an OpenCode record
        # from era A keeps its own reading, the cache read out of the prompt.
        usage = {"input": 1_000, "output": 100, "reasoning": 0, "cache": {"read": 400, "write": 0}}
        one_session_db(os.path.join(self.home, "opencode.db"), PROJECT_ID, self.repo,
                       version="1.0.30", usage=usage)
        result = oc.scan(self.repo, [self.home])
        models = next(iter(result.days.values()))["models"]
        self.assertEqual(models["openai/gpt-5.3-codex"]["input"], 600)


class TestTheDatabases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)

    def turns(self):
        days, _ = scanned(self.repo, [self.home])
        return 0 if days is None else sum(day["turns"] for day in days.values())

    def test_the_release_channel_database_is_read(self):
        kilo_db(os.path.join(self.home, "kilo.db"), self.repo)
        self.assertEqual(self.turns(), 1)

    def test_a_channel_database_is_read(self):
        kilo_db(os.path.join(self.home, "kilo-nightly.db"), self.repo)
        self.assertEqual(self.turns(), 1)

    def test_the_name_the_fork_renamed_is_still_read(self):
        # A user who switched to Kilo before the rename has their sessions in
        # opencode-<channel>.db inside the kilo directory. OpenCode's own
        # reader never looks here, so nothing else would count them.
        kilo_db(os.path.join(self.home, "opencode-beta.db"), self.repo)
        self.assertEqual(self.turns(), 1)

    def test_both_names_together_count_each_session_once(self):
        # getChannelPath() prefers the new name and leaves the old one in
        # place, so the same session can sit in both.
        shared = kilo_db(os.path.join(self.home, "kilo-beta.db"), self.repo)
        again = kilo_db(os.path.join(self.home, "opencode-beta.db"), self.repo)
        self.assertEqual(shared, again)
        self.assertEqual(self.turns(), 1)

    def test_an_unsuffixed_opencode_database_here_is_not_kilo_s(self):
        # `opencode.db` is the name OpenCode's own reader owns; only the
        # channel-suffixed form is a Kilo rename.
        kilo_db(os.path.join(self.home, "opencode.db"), self.repo)
        self.assertEqual(self.turns(), 0)

    def test_no_store_is_none(self):
        self.assertIsNone(kilo.scan(self.repo, [self.home]))


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = make_repo(os.path.join(self.tmp.name, "repo"))
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.db = os.path.join(self.home, "kilo.db")

    def common_dir(self):
        """Where the tools cache a project id. make_repo() builds a plain
        repository, so git's common directory is its own .git."""
        out = subprocess.run(["git", "-C", self.repo, "rev-parse", "--git-common-dir"],
                             check=True, capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, ".git")
        return out

    def test_the_remote_hash_is_the_id_kilo_writes(self):
        # project.ts: sha1("git-remote:" + host + "/" + path), the same id
        # OpenCode computes, so a session from any clone counts.
        self.assertIn(PROJECT_ID, kilo.known_ids(self.repo))

    def test_the_id_cached_under_kilo_is_read(self):
        path = os.path.join(self.repo, self.common_dir(), "kilo")
        with open(path, "w", encoding="utf-8") as f:
            f.write("prj_renamedremote\n")
        self.assertIn("prj_renamedremote", kilo.known_ids(self.repo))
        kilo_db(self.db, self.repo, project="prj_renamedremote")
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(sum(day["turns"] for day in days.values()), 1)

    def test_an_id_cached_under_opencode_is_not_kilo_s(self):
        # The two forks cache under different names in the same directory, so
        # reading the wrong file would claim the other tool's project.
        with open(os.path.join(self.repo, self.common_dir(), "opencode"), "w", encoding="utf-8") as f:
            f.write("prj_opencodeonly\n")
        self.assertNotIn("prj_opencodeonly", kilo.known_ids(self.repo))
        kilo_db(self.db, self.repo, project="prj_opencodeonly")
        self.assertIsNone(kilo.scan(self.repo, [self.home]))

    def test_another_project_at_our_path_needs_one_of_our_commits(self):
        kilo_db(self.db, self.repo, project="0" * 40)
        self.assertIsNone(kilo.scan(self.repo, [self.home]))


class TestTheSessionRollUp(unittest.TestCase):
    """Kilo's session_usage migration added cost and tokens_* columns to the
    session row, summed from its own messages. Counting them as well would
    double every token."""

    def test_the_roll_up_columns_are_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            sid, mid = make_id("ses", AT, 1, "rollup01"), make_id("msg", AT, 1, "rollup01")
            agent_logs.build_database(os.path.join(home, "kilo.db"), {
                "session": [{"id": sid, "project_id": PROJECT_ID, "directory": repo,
                             "version": "7.7.6", "parent_id": None, "path": "", "time_created": AT,
                             "cost": 0.5, "tokens_input": 1_000, "tokens_output": 100,
                             "tokens_reasoning": 0, "tokens_cache_read": 0, "tokens_cache_write": 0}],
                "message": [{"id": mid, "session_id": sid, "time_created": AT,
                             "data": {"role": "assistant", "modelID": "gpt-5.3-codex",
                                      "providerID": "openai", "time": {"created": AT},
                                      "tokens": USAGE, "path": {"cwd": repo, "root": repo}}}],
            })
            days, _ = scanned(repo, [home])
            day = next(iter(days.values()))
            # The message alone: 1,000 input and 100 output, counted once.
            self.assertEqual((day["turns"], tokens.source_total(day)), (1, 1_100))


# The recorded Kilo session in tests/fixtures/kilo, worked out from the
# upstream export before reduction and without this reader: four assistant
# messages, each one's `total` equal to input + output + cache read +
# reasoning, so every one of them says its reasoning sits outside the output.
#
#   input        9493 +   411 +   364 +  9890 = 20,158
#   output         34 +    98 +    86 +    47 =    265   reported
#   reasoning      34 +   153 +    37 +    17 =    241   outside, so added
#   cache read   2048 + 11264 + 11648 +  2048 = 27,008
#
# The model is the one its step-finish parts name, not the `kilo-auto/free`
# alias its messages carry.
RECORDED = {"2026-08-10": {"turns": 4, "models": {
    "kilo/stepfun/step-3.7-flash": {"input": 20_158, "output": 506,
                                    "cache_read": 27_008, "cache_write": 0}}}}


class TestTheRecording(unittest.TestCase):
    """The reduced openharness export, read where Kilo writes its store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.repo = make_repo(os.path.join(self.root, "agent-sample"))
        self.home = os.path.join(self.root, "home", "kilo")
        agent_logs.install("kilo", self.home, self.repo, database="kilo.db")

    def scan(self, repo=None):
        return kilo.scan(repo or self.repo, [self.home])

    def test_every_recorded_day_and_model(self):
        result = self.scan()
        self.assertEqual(result.days, RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_the_session_roll_up_is_not_counted_as_well(self):
        # The session row carries Kilo's own sums of these same messages
        # (20,158 input, 265 output, 241 reasoning, 27,008 cache read).
        # Counting them too would double every figure above.
        day = self.scan().days["2026-08-10"]
        self.assertEqual(tokens.source_total(day), 20_158 + 506 + 27_008)

    def test_the_model_its_router_resolved_to_is_the_one_recorded(self):
        # Every message names the alias `kilo-auto/free`, which is not a
        # model and has no price; each step-finish part names what actually
        # served the call.
        models = self.scan().days["2026-08-10"]["models"]
        self.assertEqual(list(models), ["kilo/stepfun/step-3.7-flash"])
        self.assertNotIn("kilo/kilo-auto/free", models)

    def test_a_repository_elsewhere_is_not_matched(self):
        self.assertIsNone(self.scan(os.path.join(self.root, "elsewhere")))

    def test_opencode_does_not_read_kilo_s_store(self):
        # Its data directory is Kilo's own, and the database is kilo.db.
        self.assertIsNone(oc.scan(self.repo, [self.home]))


class TestSourceContract(unittest.TestCase):
    def test_the_module_provides_what_a_source_must(self):
        for name in ("KEY", "LABEL", "AGENT", "default_homes", "scan"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(kilo, name))

    def test_its_agent_pattern_matches_the_name_the_matcher_produces(self):
        self.assertTrue(kilo.AGENT.search("Kilo Code"))

    def test_it_does_not_claim_opencode_s_commits(self):
        self.assertFalse(kilo.AGENT.search("OpenCode"))
        self.assertFalse(oc.AGENT.search("Kilo Code"))

    def test_the_counters_it_reports_are_the_archive_s_own(self):
        self.assertEqual(sorted(oc.counters(USAGE, "openai", "gpt-5.3-codex", oc.ERA_E)),
                         sorted(tokens.COUNTERS))


if __name__ == "__main__":
    unittest.main()
