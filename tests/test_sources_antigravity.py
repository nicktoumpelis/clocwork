import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from clocwork import agents
from clocwork.sources import antigravity
from tests import agent_logs

# The seven recorded conversations in tests/fixtures/antigravity (agy 1.2.8),
# summed by hand from each call's own fields: input is field 2, output field
# 3 (the thinking, field 9, with the visible reply, field 10), and cache read
# field 5, reported beside the input. Every one is placed by its CLI log.
#   342e8ba1, print mode:                            11,874 / 25
#   29ac6e7f, interactive (and its /exit record):    11,894 / 358, 12,378 / 151, 12,757 / 125
#   4b3fad79, print mode, continued twice:           11,881 / 1,046, 13,333 / 26, 13,565 / 26
#   7023721e, print mode, --add-dir <absolute>:      11,879 / 26
#   10ca56d2, print mode, --add-dir ../<relative>:   11,876 / 29
#   2d64a70a, interactive, --add-dir <absolute>:     11,915 / 25
#   80e4a8f7, print mode, Claude Sonnet 4.6, continued twice:
#                                                    13,697 / 13, 684 / 13 + 13,228 read, 358 / 13 + 13,769 read
# agy's own JSON agrees: 11,874 / 25 for the first; and for the Claude one,
# cumulatively after its third call, 14,739 input, 39 output and 26,997 cache
# read, with a total of input + output only.
RECORDED = {"2026-09-22": {"turns": 13, "models": {
    "gemini-3.8-flash": {"input": 123_352, "output": 1_837, "cache_read": 0, "cache_write": 0},
    "claude-sonnet-4-6": {"input": 14_739, "output": 39, "cache_read": 26_997, "cache_write": 0}}}}
# The interactive conversations, which history.jsonl and the summaries can
# place without the logs: 29ac6e7f and 2d64a70a.
INTERACTIVE = {"turns": 4, "models": {"gemini-3.8-flash": {
    "input": 11_894 + 12_378 + 12_757 + 11_915, "output": 358 + 151 + 125 + 25, "cache_read": 0, "cache_write": 0}}}
# The three recorded IDE conversations in tests/fixtures/antigravity-ide
# (Antigravity IDE 2.5.5), summed by hand from each step's usage, every call
# being in its step. Each has one call on model id 1050 (a step of type 23,
# 100 or 101 input and 4 or 5 output) with no generation row, so no model name.
# The IDE writes no log, history or summary: each is placed by its own
# trajectory's workspace (field 1.1).
#   092375a1, the repository opened:             6 calls, 68,023 / 943 + 36,614 read; 100 / 5
#   d79bd73f, its subdirectory sub/ opened:      9 calls, 63,751 / 1,449 + 97,576 read; 100 / 4
#   87baf5fe, a workspace of /work/elsewhere and then the repository:
#                                                6 calls, 52,412 / 874 + 52,860 read; 101 / 4
# A Gemini call's cache read is beside its input, as a Claude one's is: the
# prompt, input plus cache read, grows call by call (16,559, 16,974, then
# 5,033 + 12,210 = 17,243, ...), where a read inside the input would have it
# fall from 17k to 5k and back.
IDE_REPOSITORY = {"2026-09-22": {"turns": 17, "models": {
    "gemini-3.8-flash": {"input": 68_023 + 63_751, "output": 943 + 1_449,
                         "cache_read": 36_614 + 97_576, "cache_write": 0},
    "unknown": {"input": 200, "output": 9, "cache_read": 0, "cache_write": 0}}}}
IDE_ELSEWHERE = {"2026-09-22": {"turns": 7, "models": {
    "gemini-3.8-flash": {"input": 52_412, "output": 874, "cache_read": 52_860, "cache_write": 0},
    "unknown": {"input": 101, "output": 4, "cache_read": 0, "cache_write": 0}}}}
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

    def test_the_logs_place_every_conversation_on_their_own(self):
        os.remove(os.path.join(self.home, "conversation_summaries.db"))
        os.remove(os.path.join(self.home, "history.jsonl"))
        self.assertEqual(self.scan().days, RECORDED)

    def test_without_the_logs_the_history_places_the_interactive_ones(self):
        # Without the summaries too, so that only the history can place
        # them: the five print-mode conversations are held.
        shutil.rmtree(os.path.join(self.home, "log"))
        os.remove(os.path.join(self.home, "conversation_summaries.db"))
        result = self.scan()
        self.assertEqual((result.days["2026-09-22"], result.held), (INTERACTIVE, 5))

    def test_without_the_logs_or_the_history_the_summary_s_last_uri_does(self):
        shutil.rmtree(os.path.join(self.home, "log"))
        os.remove(os.path.join(self.home, "history.jsonl"))
        result = self.scan()
        self.assertEqual((result.days["2026-09-22"], result.held), (INTERACTIVE, 4))

    def test_an_added_directory_is_not_the_workspace_while_the_log_is_there(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        self.assertTrue(os.path.isdir(elsewhere))  # made by install()
        self.assertIsNone(self.scan(elsewhere))

    def test_the_claude_calls_report_their_cache_read_beside_the_input(self):
        self.assertEqual(self.scan().days["2026-09-22"]["models"]["claude-sonnet-4-6"],
                         {"input": 14_739, "output": 39, "cache_read": 26_997, "cache_write": 0})


class TestIdeRecordings(Home):
    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.root, "home", ".gemini", "antigravity-ide")
        agent_logs.install("antigravity-ide", self.home, self.repo)
        self.elsewhere = os.path.join(self.root, "elsewhere")

    def test_every_recorded_call_is_placed_by_its_own_workspace(self):
        result = self.scan()
        self.assertEqual((result.days, result.held, result.malformed, result.skipped), (IDE_REPOSITORY, 0, 0, 0))

    def test_a_workspace_of_several_folders_is_its_first_folder_s(self):
        self.assertEqual(self.scan(self.elsewhere).days, IDE_ELSEWHERE)


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

    def exit(self, cid, workspace):
        with open(os.path.join(self.home, "history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": 1, "workspace": workspace, "conversationId": cid,
                                "type": "slash_command"}) + "\n")

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

    def test_the_cache_counts_are_beside_the_input(self):
        # As a recorded Claude call has them: 684 input beside 13,228 read.
        self.conversation(steps=[self.step(usage(684, 13, cache_read=13_228, cache_write=40))],
                          workspace=self.uri())
        self.assertEqual(self.day()["models"]["unknown"], counts(684, 13, 13_228, 40))

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

    def test_a_summary_s_last_workspace_is_the_working_directory(self):
        # agy lists the --add-dir directories first.
        other = os.path.join(self.root, "other")
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(other) + self.uri())
        self.conversation(cid="c2", steps=[self.step(usage(7, 1, "c2"))], workspace=self.uri() + self.uri(other))
        self.assertEqual(self.day()["models"]["unknown"], counts(100, 1))

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

    def test_the_log_wins_over_the_history_and_the_summary(self):
        other = os.path.join(self.root, "other")
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(other), logged=self.repo)
        self.exit("c1", other)
        self.assertEqual(self.day()["turns"], 1)

    def test_the_history_wins_over_the_summary(self):
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(os.path.join(self.root, "other")))
        self.exit("c1", self.repo)
        self.assertEqual(self.day()["turns"], 1)

    def test_a_history_line_that_is_not_json_is_passed_over(self):
        self.conversation(steps=[self.step(usage(100, 1))])
        with open(os.path.join(self.home, "history.jsonl"), "w", encoding="utf-8") as f:
            f.write("not json\n[1]\n")
        self.exit("c1", self.repo)
        self.assertEqual(self.day()["turns"], 1)

    def test_a_home_relative_added_directory_in_a_log(self):
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} ~/x")
        self.assertEqual(self.day()["turns"], 1)

    def test_a_log_that_cannot_be_told_falls_through_to_the_history(self):
        # A bare relative --add-dir is logged as typed: nothing marks where
        # the first directory ends.
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} docs")
        self.exit("c1", self.repo)
        self.assertEqual(self.day()["turns"], 1)

    def test_a_log_that_cannot_be_told_does_not_fall_through_to_the_summary(self):
        # In print mode the summary names only the added directory, so it
        # would credit the run to that directory.
        docs = os.path.join(self.root, "docs")
        os.makedirs(docs)
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} docs", workspace=self.uri(docs))
        self.conversation(cid="c2", steps=[self.step(usage(7, 1, "c2"))], logged=self.repo)
        self.assertIsNone(self.scan(docs))
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["unknown"], result.held), (counts(7, 1), 1))

    def test_a_log_that_cannot_be_told_and_nothing_else_is_held(self):
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} docs")
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["turns"], result.held), (1, 1))

    def test_a_deleted_sibling_with_a_dot_is_not_the_repository(self):
        self.conversation(steps=[self.step(usage(100, 1))], logged=self.repo + " .old")
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], logged=self.repo + " ~x")
        self.assertIsNone(self.scan())

    def test_a_relative_directory_in_the_history_is_no_workspace(self):
        self.conversation(steps=[self.step(usage(100, 1))])
        self.exit("c1", ".")
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.assertIsNone(self.scan())

    def test_the_history_s_first_record_places_a_conversation(self):
        self.conversation(steps=[self.step(usage(100, 1))])
        self.exit("c1", self.repo)
        self.exit("c1", os.path.join(self.root, "other"))
        self.assertEqual(self.day()["turns"], 1)

    def test_a_relative_added_directory_in_a_log(self):
        # agy logs --add-dir ../x as typed.
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} ../x")
        self.assertEqual(self.day()["turns"], 1)

    def test_a_conversation_s_own_workspace_places_it_when_nothing_else_does(self):
        # The IDE's way: field 1 of the trajectory, whose field 1 is the
        # folder opened (2 is its git root).
        self.conversation(steps=[self.step(usage(100, 1))],
                          trajectory={"1": {"1": self.uri(os.path.join(self.repo, "src"))[0], "2": self.uri()[0]}})
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["turns"], result.held), (1, 0))

    def test_the_first_of_several_folders_is_the_workspace(self):
        other = os.path.join(self.root, "other")
        trajectory = {"1": [{"1": self.uri(other)[0]}, {"1": self.uri()[0]}]}
        # Both folders are written, so the second is there to be passed over.
        self.assertEqual([n for n, _ in antigravity.pairs(agent_logs.protobuf(trajectory))], [1, 1])
        self.conversation(steps=[self.step(usage(100, 1))], trajectory=trajectory)
        self.assertIsNone(self.scan())
        self.assertEqual(self.scan(other).days["2026-08-05"]["turns"], 1)

    def test_the_summary_wins_over_the_conversation_s_own_workspace(self):
        # The CLI's placement is unchanged by the IDE's: its own workspace
        # is the last resort.
        other = os.path.join(self.root, "other")
        self.conversation(steps=[self.step(usage(100, 1))], workspace=self.uri(other),
                          trajectory={"1": {"1": self.uri()[0]}})
        self.assertIsNone(self.scan())
        self.assertEqual(self.scan(other).days["2026-08-05"]["turns"], 1)

    def test_a_conversation_s_own_workspace_on_another_host_is_none(self):
        self.conversation(steps=[self.step(usage(100, 1))], trajectory={"1": {"1": "file://elsewhere" + self.repo}})
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], trajectory={"1": {"1": "not a uri"}})
        self.conversation(cid="c3", steps=[self.step(usage(7, 1, "c3"))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["unknown"], result.held), (counts(7, 1), 2))

    def test_a_logged_conversation_is_not_placed_by_its_own_workspace(self):
        # A log that cannot be told falls through to the history alone.
        self.conversation(steps=[self.step(usage(100, 1))], logged=f"{self.repo} docs",
                          trajectory={"1": {"1": self.uri()[0]}})
        self.conversation(cid="c2", steps=[self.step(usage(7, 1, "c2"))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["unknown"], result.held), (counts(7, 1), 1))

    def test_a_folder_s_git_root_is_not_its_workspace(self):
        # 1.2 is the git root of the folder opened, which is 1.1.
        self.conversation(steps=[self.step(usage(100, 1))], trajectory={"1": {"2": self.uri()[0]}})
        self.conversation(cid="c2", steps=[self.step(usage(7, 1, "c2"))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["unknown"], result.held), (counts(7, 1), 1))

    def test_a_conversation_placed_nowhere_that_will_not_open_is_held(self):
        path = os.path.join(self.home, "conversations", "c1.db")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"not a database")
        self.conversation(cid="c2", steps=[self.step(usage(100, 1, "c2"))], workspace=self.uri())
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["turns"], result.held, result.skipped), (1, 1, 0))

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
