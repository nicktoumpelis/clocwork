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
        # rename is still read where the new name is absent. The renamed name
        # is first, because it is the older one.
        self.assertEqual(kilo.STORE.databases, ("opencode-*.db", "kilo*.db"))

    def test_opencode_does_not_read_kilo_s_databases(self):
        self.assertEqual(oc.OPENCODE.databases, ("opencode*.db",))

    def test_kilo_caches_its_project_id_under_its_own_name(self):
        # project.ts reads path.join(commonDirectory, "kilo"), marked
        # kilocode_change where OpenCode reads "opencode".
        self.assertEqual((kilo.STORE.cache_name, oc.OPENCODE.cache_name), ("kilo", "opencode"))

    def test_both_stores_read_the_file_generations(self):
        # Kilo's database arrived in v7.0.26; up to v1.0.25 it shipped
        # OpenCode's JSON store, writing to its own directory already
        # (`const app = "kilo"` is there at v1.0.25), and that release
        # carries the J0-to-J1 migration -- so both layouts can sit in it.
        self.assertTrue(kilo.STORE.file_stores)
        self.assertTrue(oc.OPENCODE.file_stores)

    def test_a_file_store_in_kilo_s_directory_is_read(self):
        # The behaviour the flag above buys: a v1.0.x release wrote this
        # tree, so skipping it would lose every token Kilo spent before its
        # database existed.
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
            models = next(iter(kilo.scan(repo, [home]).days.values()))["models"]
            # The usage itself, not merely a day: a scan that returned
            # something would prove nothing, since one unreadable file is
            # enough for that.
            self.assertEqual(models["openai/gpt-5.3-codex"],
                             {"input": 1_000, "output": 100, "cache_read": 0, "cache_write": 0})

    def test_a_record_the_upgrade_copied_into_the_database_is_counted_once(self):
        # Reading both stores is only safe because a record the migrations
        # copied keeps its id: a user who ran v1.0.25 and then v7.x has the
        # same call in the JSON tree and in kilo.db, and counting it twice
        # would double every token they spent before the upgrade.
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            sid = make_id("ses", AT, 1, "kilocase01")
            mid = make_id("msg", AT, 1, "kilocase01")
            root = os.path.join(home, "storage")
            for table, doc in (("session", {"id": sid, "projectID": PROJECT_ID,
                                            "directory": repo, "version": "1.1.60"}),
                               ("message", {"id": mid, "sessionID": sid,
                                            "role": "assistant", "providerID": "openai",
                                            "modelID": "gpt-5.3-codex", "time": {"created": AT},
                                            "tokens": USAGE})):
                d = os.path.join(root, table, sid)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, f"{doc['id']}.json"), "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            # kilo_db() mints the same two ids from the same (AT, tail).
            self.assertEqual(kilo_db(os.path.join(home, "kilo.db"), repo), sid)
            models = next(iter(kilo.scan(repo, [home]).days.values()))["models"]
            self.assertEqual(models["openai/gpt-5.3-codex"],
                             {"input": 1_000, "output": 100, "cache_read": 0, "cache_write": 0})

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
            overlapping = kilo.STORE._replace(databases=("kilo*.db", "kilo-*.db"))
            self.assertEqual(oc.scan(repo, [home], overlapping).skipped, 1)

    def test_only_kilo_floors_the_era(self):
        self.assertEqual(kilo.STORE.floor, oc.ERA_B)
        self.assertEqual(oc.OPENCODE.floor, ())


class TestTheReleaseTable(unittest.TestCase):
    """Which OpenCode release each Kilo release carried. The rows come from
    git ancestry in the fork (see RELEASES), so these tests pin the facts the
    counter rules depend on rather than restating every row."""

    def carried(self, text):
        return kilo.carried(oc.version_of(text))

    def test_both_columns_only_ever_rise(self):
        # bisect needs the Kilo column sorted, and "newer than the table
        # carried at least the last row" needs the OpenCode column to rise
        # with it; a mistyped row breaks one or the other.
        firsts = [k for k, _ in kilo.RELEASES]
        carried = [u for _, u in kilo.RELEASES]
        self.assertEqual(firsts, sorted(set(firsts)))
        self.assertEqual(carried, sorted(set(carried)))

    def test_no_kilo_release_carried_era_a_or_era_c(self):
        # The two rules that take a cache read back out of the prompt. Kilo's
        # first release, 1.0.0, already carried v1.1.36, and it
        # went from v1.2.25 to v1.3.13 in one step, past era C's two releases.
        self.assertTrue(kilo.RELEASES)
        for first, upstream in kilo.RELEASES:
            with self.subTest(kilo=first):
                self.assertGreaterEqual(upstream, oc.ERA_B)
                self.assertFalse(oc.ERA_C <= upstream < oc.ERA_D)

    def test_the_releases_either_side_of_two_era_boundaries(self):
        self.assertTrue(oc.ERA_B <= self.carried("7.2.4") < oc.ERA_C)
        self.assertTrue(oc.ERA_D <= self.carried("7.2.5") < oc.ERA_E)
        self.assertGreaterEqual(self.carried("7.2.6"), oc.ERA_E)

    def test_a_release_between_two_rows_carried_the_earlier_row(self):
        # v7.2.7 to v7.2.16 all carried v1.4.3.
        self.assertEqual(self.carried("7.2.10"), (1, 4, 3))

    def test_a_release_newer_than_the_table_carried_at_least_its_last_row(self):
        self.assertEqual(self.carried("9.0.0"), kilo.RELEASES[-1][1])

    def test_the_untagged_npm_releases_carried_the_first_row(self):
        # Kilo's 1.0.0 to 1.0.12 were published to npm with no tag of their
        # own -- the fork's v1.0.x tags up to there are OpenCode's commits --
        # from a main line that descended from v1.1.36 throughout.
        for text in ("1.0.0", "1.0.9", "1.0.12"):
            with self.subTest(version=text):
                self.assertEqual(self.carried(text), (1, 1, 36))

    def test_a_version_no_kilo_release_had_is_not_mapped(self):
        # "local" is a build from source, and 0.x is the CLI Kilo shipped
        # before the fork, which never wrote this store: neither says what a
        # record's counters mean, so the floor decides.
        for text in ("local", "", "0.26.0"):
            with self.subTest(version=text):
                self.assertEqual(self.carried(text), ())

    def test_opencode_s_own_versions_are_its_releases(self):
        self.assertEqual(oc.OPENCODE.carried((1, 3, 4)), (1, 3, 4))


class TestTheEra(unittest.TestCase):
    """A Kilo version is read at the era of the OpenCode release it carried.
    Where it names none this reader knows, the floor stands in: not a claim
    about the rule that applied, only a bar against era A, the one subtracting
    rule a version-less record can reach -- era C also subtracts, but needs a
    version in [ERA_C, ERA_D) and an Anthropic-shaped provider."""

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

    def test_a_7x_release_before_v7_2_6_is_read_before_era_e(self):
        # 7.x compares above v1.3.16 as a number, but v7.0.26 to v7.2.5
        # carried v1.2.2 to v1.3.13. With no total, the provider decides
        # there, and OpenAI's reasoning was inside the output.
        usage = {"input": 1_000, "output": 100, "reasoning": 40, "cache": {"read": 0, "write": 0}}
        for version in ("7.0.26", "7.2.5"):
            with self.subTest(version=version):
                self.assertEqual(self.day(version, usage)["openai/gpt-5.3-codex"]["output"], 100)
        self.assertEqual(self.day("7.2.6", usage)["openai/gpt-5.3-codex"]["output"], 140)

    def test_a_release_newer_than_the_table_is_read_at_its_last_row(self):
        usage = {"input": 1_000, "output": 100, "reasoning": 40, "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.day("9.0.0", usage)["openai/gpt-5.3-codex"]["output"], 140)

    def test_an_unmapped_version_is_floored_not_read_as_era_a(self):
        # 0.26.0 is below ERA_B as a number, and no release of this store
        # had it.
        usage = {"input": 1_000, "output": 100, "reasoning": 0, "cache": {"read": 400, "write": 0}}
        self.assertEqual(self.day("0.26.0", usage)["openai/gpt-5.3-codex"]["input"], 1_000)

    def test_a_local_build_s_v2_row_is_still_read_as_the_table_s_release(self):
        # session_message arrived in OpenCode v1.14.34, so a row in it is at
        # era E whatever its session names. That floor is an OpenCode
        # version, and must not be mistaken for a Kilo one and mapped down:
        # Kilo "1.14.34" would fall in the table's 1.0.24 row, before era E.
        usage = {"input": 1_000, "output": 100, "reasoning": 40, "cache": {"read": 0, "write": 0}}
        sid, mid = make_id("ses", AT, 1, "kilov2case"), make_id("msg", AT, 1, "kilov2case")
        agent_logs.build_database(os.path.join(self.home, "kilo.db"), {
            "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                         "version": "local", "parent_id": None, "path": "", "time_created": AT}],
            "message": [{"id": make_id("msg", AT, 8, "kilov2case"), "session_id": sid,
                         "time_created": AT, "data": {"role": "user", "time": {"created": AT}}}],
            "session_message": [{"id": mid, "session_id": sid, "type": "assistant", "seq": 1,
                                 "time_created": AT,
                                 "data": {"role": "assistant", "modelID": "gpt-5.3-codex",
                                          "providerID": "openai", "time": {"created": AT},
                                          "tokens": usage,
                                          "path": {"cwd": self.repo, "root": self.repo}}}],
        })
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(next(iter(days.values()))["models"]["openai/gpt-5.3-codex"]["output"], 140)

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

    def test_the_floor_stops_at_era_b_and_leaves_the_later_rules_alone(self):
        # The floor is ERA_B, not the newest era, so a record with neither a
        # total nor a usable version keeps the pre-era-E reading: the
        # provider decides, and this one's reasoning was inside the output.
        # A record whose release carried era E still gets era E's rule,
        # which counts the reasoning outside.
        usage = {"input": 1_000, "output": 100, "reasoning": 40, "cache": {"read": 0, "write": 0}}
        self.assertEqual(self.day("local", usage)["openai/gpt-5.3-codex"]["output"], 100)
        self.assertEqual(self.day("7.7.6", usage)["openai/gpt-5.3-codex"]["output"], 140)

    def test_a_record_that_carries_a_total_is_still_believed_over_the_floor(self):
        # The floor is a default, not a rule: a total is evidence, and here
        # it says the reasoning is already inside the output.
        usage = {"total": 1_140, "input": 1_000, "output": 140, "reasoning": 40,
                 "cache": {"read": 0, "write": 0}}
        models = self.day("7.7.6", usage)
        self.assertEqual(models["openai/gpt-5.3-codex"]["output"], 140)

    def test_opencode_still_reads_its_own_oldest_era(self):
        # Neither the floor nor the table may leak into the other source: an
        # OpenCode record
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

    def test_the_current_name_wins_over_the_one_it_renamed(self):
        # The rename leaves the old file in place, frozen, while the new one
        # goes on being written. Reading them in name order would let the
        # frozen copy overwrite the current record, which is the reverse of
        # what read_home promises.
        sid, mid, pid = (make_id("ses", AT, 1, "order01"), make_id("msg", AT, 1, "order01"),
                         "prt_order01")

        def build(name, output):
            agent_logs.build_database(os.path.join(self.home, name), {
                "session": [{"id": sid, "project_id": PROJECT_ID, "directory": self.repo,
                             "version": "7.7.6", "parent_id": None, "path": "",
                             "time_created": AT}],
                "message": [{"id": mid, "session_id": sid, "time_created": AT,
                             "data": {"role": "assistant", "modelID": "m", "providerID": "p",
                                      "time": {"created": AT}}}],
                "part": [{"id": pid, "message_id": mid, "session_id": sid, "time_created": AT,
                          "data": {"type": "step-finish",
                                   "tokens": {"input": 10, "output": output, "reasoning": 0,
                                              "cache": {"read": 0, "write": 0}}}}],
            })

        build("opencode-beta.db", 1)        # frozen at the rename
        build("kilo-beta.db", 999)          # written since
        days, _ = scanned(self.repo, [self.home])
        self.assertEqual(next(iter(days.values()))["models"]["p/m"]["output"], 999)

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


class TestThePartModel(unittest.TestCase):
    """A step-finish part that names its own model names the record -- but
    only when it names the whole of it."""

    def test_a_part_that_names_both_halves_is_used(self):
        self.assertEqual(oc.step_model({"type": "step-finish",
                                        "model": {"providerID": "kilo", "modelID": "x/y"}}),
                         ("kilo", "x/y"))

    def test_a_part_that_names_half_is_not_used(self):
        # Pairing the part's provider with the message's model, or the
        # reverse, names a combination that never served a call -- and the
        # provider is what anthropic_like() reads, so a crossed pair can
        # change the arithmetic and not just the label.
        for half in ({"providerID": "openrouter"}, {"modelID": "gpt-5"},
                     {"providerID": "openrouter", "modelID": ""},
                     {"providerID": "", "modelID": "gpt-5"}):
            with self.subTest(half=half):
                self.assertEqual(oc.step_model({"type": "step-finish", "model": half}),
                                 (None, None))

    def test_a_part_with_no_model_or_a_malformed_one_is_not_used(self):
        for value in (None, [], "", 7, {}):
            with self.subTest(value=value):
                self.assertEqual(oc.step_model({"type": "step-finish", "model": value}),
                                 (None, None))
        self.assertEqual(oc.step_model({"type": "step-finish"}), (None, None))

    def test_a_half_named_part_keeps_the_message_s_own_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(os.path.join(tmp, "repo"))
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            sid, mid = make_id("ses", AT, 1, "half0001"), make_id("msg", AT, 1, "half0001")
            agent_logs.build_database(os.path.join(home, "kilo.db"), {
                "session": [{"id": sid, "project_id": PROJECT_ID, "directory": repo,
                             "version": "7.7.6", "parent_id": None, "path": "",
                             "time_created": AT}],
                "message": [{"id": mid, "session_id": sid, "time_created": AT,
                             "data": {"role": "assistant", "modelID": "claude-sonnet-4.5",
                                      "providerID": "anthropic", "time": {"created": AT}}}],
                "part": [{"id": "prt_half0001", "message_id": mid, "session_id": sid,
                          "time_created": AT,
                          "data": {"type": "step-finish", "model": {"providerID": "openrouter"},
                                   "tokens": {"input": 10, "output": 2, "reasoning": 0,
                                              "cache": {"read": 0, "write": 0}}}}],
            })
            days, _ = scanned(repo, [home])
            self.assertEqual(list(next(iter(days.values()))["models"]),
                             ["anthropic/claude-sonnet-4.5"])


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
