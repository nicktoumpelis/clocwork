import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from clocwork import agents
from clocwork.sources import antigravity
from tests import agent_logs

# The three recorded conversations in tests/fixtures/antigravity (agy 1.2.8,
# Gemini 3.8 Flash), summed by hand from each call's own fields:
# input is field 2 and output field 3, which holds the thinking (field 9)
# with the visible reply (field 10); no call read or wrote a cache.
#   342e8ba1, print mode, placed by its CLI log:    11,874 / 25
#   29ac6e7f, interactive, placed by its summary:   11,894 / 358, 12,378 / 151, 12,757 / 125
#   4b3fad79, print mode then continued twice:      11,881 / 1,046, 13,333 / 26, 13,565 / 26
# agy's own JSON output agrees: 11,874 / 25 for the first, and 11,881 / 1,046
# for the third's first call.
RECORDED = {"2026-09-22": {"turns": 7, "models": {
    "gemini-3.8-flash": {"input": 87_682, "output": 1_757, "cache_read": 0, "cache_write": 0}}}}
INTERACTIVE = "29ac6e7f-cce9-48d3-b2bc-ce3f90e37016"
MODEL = "gemini-3.8-flash"


def counts(input=0, output=0, cache_read=0, cache_write=0):
    return {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write}


def usage(input=0, output=0, rid="r1", model=1318, cache_read=None, cache_write=None):
    u = {"1": model, "2": input, "3": output, "11": rid}
    if cache_read is not None:
        u["5"] = cache_read
    if cache_write is not None:
        u["4"] = cache_write
    return u


def at(seconds):
    return {"1": seconds, "2": 0}


# 2026-08-05T10:00:00Z and a day later.
DAY, NEXT = 1_785_924_000, 1_786_010_400


class TestHomes(unittest.TestCase):
    def test_the_cli_and_the_ide_directories(self):
        home = os.path.expanduser("~")
        self.assertEqual(antigravity.default_homes({}),
                         [os.path.join(home, ".gemini", name)
                          for name in ("antigravity-cli", "antigravity", "antigravity-ide", "antigravity-backup")])


class TestAttribution(unittest.TestCase):
    def test_a_trailer_naming_antigravity_is_its_agent(self):
        name = agents.detect_agent("Fix\n\nCo-authored-by: Antigravity <antigravity@google.com>\n")
        self.assertEqual(name, "Antigravity")
        self.assertTrue(antigravity.AGENT.search(name))


class Home(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".gemini", "antigravity-cli")
        os.makedirs(self.home)

    def scan(self, repo=None, homes=None):
        return antigravity.scan(repo or self.repo, [self.home] if homes is None else homes)


class TestRecordings(Home):
    def setUp(self):
        super().setUp()
        agent_logs.install("antigravity", self.home, self.repo)

    def test_every_recorded_call(self):
        self.assertEqual(self.scan().days, RECORDED)

    def test_a_repository_elsewhere_is_not_matched(self):
        self.assertIsNone(self.scan(os.path.join(self.root, "elsewhere")))

    def test_the_summaries_place_the_interactive_conversation_alone(self):
        shutil.rmtree(os.path.join(self.home, "log"))
        result = self.scan()
        self.assertEqual((result.days["2026-09-22"]["turns"],
                          result.days["2026-09-22"]["models"][MODEL]["input"], result.held),
                         (3, 11_894 + 12_378 + 12_757, 2))

    def test_the_logs_place_every_conversation_without_the_summaries(self):
        os.remove(os.path.join(self.home, "conversation_summaries.db"))
        self.assertEqual(self.scan().days, RECORDED)


class TestRules(Home):
    def conversation(self, cid="c1", steps=(), gens=(), trajectory=None, workspace=None, logged=None):
        """One conversation database, and where it says it ran: in the
        summaries (`workspace`) or in a CLI log (`logged`)."""
        tables = {"steps": [{"idx": i, "step_type": 15, "metadata": agent_logs.protobuf(m)}
                            for i, m in enumerate(steps)],
                  "gen_metadata": [{"idx": i, "data": agent_logs.protobuf(g)} for i, g in enumerate(gens)]}
        tables = {name: rows for name, rows in tables.items() if rows}
        if trajectory is not None:
            tables["trajectory_metadata_blob"] = [{"id": "main", "data": agent_logs.protobuf(trajectory)}]
        agent_logs.build_database(os.path.join(self.home, "conversations", cid + ".db"), tables)
        if workspace is not None:
            self.summary(cid, workspace)
        if logged is not None:
            self.log(cid, logged)

    def summary(self, cid, workspace):
        path = os.path.join(self.home, "conversation_summaries.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id, workspace_uris)")
        uris = workspace if isinstance(workspace, str) else json.dumps(workspace)
        conn.execute("INSERT INTO conversation_summaries VALUES (?, ?)", (cid, uris))
        conn.commit()
        conn.close()

    def log(self, cid, dirs, name=None):
        path = os.path.join(self.home, "log", name or f"cli-{cid}.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(agent_logs.AGY_WORKSPACE.format(dirs, self.home))
            f.write(agent_logs.AGY_CREATED.format(cid))

    def uri(self, path=None):
        return ["file://" + (path or self.repo)]

    def step(self, u, seconds=DAY):
        return {"1": at(seconds), "9": u}

    def gen(self, u, model=MODEL):
        return {"1": {"4": u, "19": model}}

    def day(self, date="2026-08-05"):
        return self.scan().days[date]

    def test_a_call_in_its_step_and_its_generation_is_counted_once(self):
        self.conversation(steps=[self.step(usage(100, 7))], gens=[self.gen(usage(100, 7))], workspace=self.uri())
        self.assertEqual(self.day(), {"turns": 1, "models": {MODEL: counts(100, 7)}})

    def test_output_holds_the_thinking_already(self):
        u = usage(100, 25)
        u.update({"9": 24, "10": 1})
        self.conversation(steps=[self.step(u)], gens=[self.gen(u)], workspace=self.uri())
        self.assertEqual(self.day()["models"][MODEL], counts(100, 25))

    def test_the_cache_read_comes_out_of_the_input(self):
        # Gemini's convention, unconfirmed here: no recorded call read a cache.
        self.conversation(steps=[self.step(usage(1_000, 5, cache_read=300, cache_write=40))],
                          workspace=self.uri())
        self.assertEqual(self.day()["models"]["unknown"], counts(700, 5, 300, 40))

    def test_each_call_on_its_step_s_day(self):
        self.conversation(steps=[self.step(usage(100, 1, "a")), self.step(usage(10, 1, "b"), NEXT)],
                          gens=[self.gen(usage(100, 1, "a")), self.gen(usage(10, 1, "b"))], workspace=self.uri())
        days = self.scan().days
        self.assertEqual((days["2026-08-05"]["models"][MODEL]["input"],
                          days["2026-08-06"]["models"][MODEL]["input"]), (100, 10))

    def test_a_step_takes_its_model_from_its_generation_or_the_same_model_id(self):
        self.conversation(steps=[self.step(usage(100, 1, "a")), self.step(usage(10, 1, "b"))],
                          gens=[self.gen(usage(100, 1, "a"))], workspace=self.uri())
        self.assertEqual(self.day()["models"], {MODEL: counts(110, 2)})

    def test_a_generation_with_no_step_takes_the_trajectory_s_day(self):
        self.conversation(gens=[self.gen(usage(100, 1))], trajectory={"2": at(NEXT)}, workspace=self.uri())
        self.assertEqual(self.day("2026-08-06")["models"][MODEL], counts(100, 1))

    def test_a_call_with_no_day_is_counted(self):
        self.conversation(gens=[self.gen(usage(100, 1))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_a_time_out_of_range_is_no_day(self):
        # agy writes u64::MAX in time-shaped fields.
        self.conversation(steps=[{"1": at(2**64 - 1), "9": usage(100, 1)}], trajectory={"2": at(2**63)},
                          workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_a_field_9_with_no_count_does_not_displace_the_call(self):
        # A step whose field 9 is not a usage message, sharing a real call's
        # response id, must not stand in for that call's record.
        self.conversation(steps=[{"1": at(NEXT), "9": {"11": "r1", "2": "many"}}],
                          gens=[self.gen(usage(100, 1))], trajectory={"2": at(DAY)}, workspace=self.uri())
        self.assertEqual(self.day()["models"][MODEL], counts(100, 1))

    def test_a_call_with_no_id_is_its_own(self):
        a, b = usage(100, 1), usage(10, 1)
        del a["11"], b["11"]
        self.conversation(steps=[self.step(a), self.step(b)], workspace=self.uri())
        self.assertEqual(self.day()["models"]["unknown"], counts(110, 2))

    def test_a_blob_that_is_not_protobuf_is_counted(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri())
        conn = sqlite3.connect(os.path.join(self.home, "conversations", "c1.db"))
        conn.execute("INSERT INTO steps (idx, step_type, metadata) VALUES (5, 15, ?)", (b"\xff\xff\xff",))
        conn.commit()
        conn.close()
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["unknown"], result.malformed), (counts(100, 1), 1))

    def test_a_database_that_will_not_open_is_skipped(self):
        path = os.path.join(self.home, "conversations", "c1.db")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"not a database")
        self.summary("c1", self.uri())
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_a_database_without_the_tables_is_skipped(self):
        agent_logs.build_database(os.path.join(self.home, "conversations", "c1.db"), {"other": [{"a": 1}]})
        self.summary("c1", self.uri())
        self.assertEqual(self.scan().skipped, 1)

    def test_an_encrypted_ide_conversation_is_not_read(self):
        os.makedirs(os.path.join(self.home, "conversations"))
        with open(os.path.join(self.home, "conversations", "c1.pb"), "wb") as f:
            f.write(b"\x00encrypted")
        self.summary("c1", self.uri())
        self.assertIsNone(self.scan())

    def test_a_subdirectory_belongs(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(os.path.join(self.repo, "src")))
        self.assertEqual(self.day()["turns"], 1)

    def test_a_sibling_whose_name_starts_the_same_is_not_the_repository(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(self.repo + "-other"),
                          logged=self.repo + "-other")
        self.assertIsNone(self.scan())

    def test_the_first_workspace_is_the_one_that_counts(self):
        other = os.path.join(self.root, "other")
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(other) + self.uri())
        self.assertIsNone(self.scan())

    def test_a_percent_encoded_workspace_is_decoded(self):
        repo = os.path.join(self.root, "my repo")
        os.makedirs(repo)
        self.conversation(steps=[self.step(usage(100, 1))], workspace=["file://" + repo.replace(" ", "%20")])
        self.assertEqual(self.scan(repo).days["2026-08-05"]["turns"], 1)

    def test_a_log_names_the_workspace_of_a_print_mode_conversation(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace="", logged=self.repo)
        self.assertEqual(self.day()["turns"], 1)

    def test_a_log_s_further_directories_are_not_the_workspace(self):
        # agy prints --add-dir directories after the first, space-separated.
        other = os.path.join(self.root, "other")
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} {other}")
        self.assertEqual(self.day()["turns"], 1)
        # Its own response id, so a wrong match would add a turn rather
        # than overwrite the first conversation's call.
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], logged=f"{other} {self.repo}")
        self.assertEqual(self.day()["turns"], 1)

    def test_a_workspace_with_a_space_in_its_log(self):
        repo = os.path.join(self.root, "my repo")
        os.makedirs(repo)
        self.conversation(steps=[self.step(usage(100, 1))], logged=repo)
        self.assertEqual(self.scan(repo).days["2026-08-05"]["turns"], 1)

    def test_a_sibling_named_like_the_repository_and_a_space_is_not_it(self):
        # "MyApp 2" is how iCloud names a duplicate of "MyApp".
        sibling = self.repo + " 2"
        os.makedirs(sibling)
        self.conversation(steps=[self.step(usage(100, 1))], logged=sibling)
        self.assertIsNone(self.scan())

    def test_a_deleted_sibling_named_like_the_repository_and_a_space_is_not_it(self):
        # The run's directory is gone, so no longer part of the text is a
        # directory; the repository's own path must not be taken for it.
        self.conversation(steps=[self.step(usage(100, 1))], logged=self.repo + " 2")
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))],
                          logged=f"{self.repo} 2 {os.path.join(self.root, 'gone')}")
        self.assertIsNone(self.scan())

    def test_a_workspace_that_will_not_parse_is_no_workspace(self):
        # One damaged summary row must not stop every source's scan.
        self.conversation(steps=[self.step(usage(100, 1))], workspace=["file://[bad/x"])
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], workspace=["file:///a%00b"])
        self.conversation(cid="c3", steps=[self.step(usage(100, 1, "c3"))], logged="/tmp/a\x00b")
        self.conversation(cid="c4", steps=[self.step(usage(100, 1, "c4"))], workspace=self.uri())
        result = self.scan()
        # The unparseable URI leaves c1 unplaced; the NUL paths place c2 and
        # c3 in no directory at all.
        self.assertEqual((result.days["2026-08-05"]["turns"], result.held), (1, 1))

    def test_a_call_with_no_counts_is_no_turn(self):
        self.conversation(steps=[self.step(usage(0, 0)), self.step(usage(100, 1, "b"))], workspace=self.uri())
        self.assertEqual(self.day()["turns"], 1)

    def test_a_relative_directory_in_a_log_is_no_workspace(self):
        self.conversation(steps=[self.step(usage(100, 1))], logged=".")
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.assertIsNone(self.scan())

    def test_a_uri_on_another_host_is_no_workspace(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=["file://elsewhere" + self.repo])
        self.assertIsNone(self.scan())

    def test_the_summary_wins_over_the_log(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(os.path.join(self.root, "other")),
                          logged=self.repo)
        self.assertIsNone(self.scan())

    def test_a_conversation_placed_nowhere_is_held(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri())
        self.conversation(cid="c2", steps=[self.step(usage(5, 1, "x"))], workspace="")
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["turns"], result.held), (1, 1))

    def test_a_home_named_twice_is_read_once(self):
        # A call with no response id is keyed by its file, so a second
        # reading of the same home would count it again.
        u = usage(100, 1)
        del u["11"]
        self.conversation(steps=[self.step(u)], workspace=self.uri())
        result = self.scan(homes=[self.home, os.path.join(self.home, ".")])
        self.assertEqual(result.days["2026-08-05"]["models"]["unknown"], counts(100, 1))

    def test_no_conversations_is_none(self):
        self.assertIsNone(self.scan())


if __name__ == "__main__":
    unittest.main()
