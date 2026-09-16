import json
import os
import tempfile
import unittest

from clocwork import tokens as tu
from clocwork.sources import gemini
from tests import agent_logs
from tests import repo_fixture as fx

# The four Irrlicht recordings, computed before reduction and without the
# reader: token-bearing messages de-duplicated by id, input less cached plus
# tool, output plus thoughts.
RECORDED = {"2026-06-12": {"turns": 19, "models": {
    "gemini-3.5-flash": {"input": 131_302, "output": 3_345, "cache_read": 0, "cache_write": 0},
    "gemini-2.5-pro": {"input": 41_841, "output": 936, "cache_read": 60_720, "cache_write": 0}}}}
REWIND = "tmp/agent-sample/chats/session-2026-06-12T10-55-ca28c1ad.jsonl"
TS = "2026-09-01T10:00:00.000Z"


def meta(repo, sid="s1", kind="main"):
    return {"sessionId": sid, "projectHash": agent_logs.project_hash(repo), "startTime": TS,
            "lastUpdated": TS, "kind": kind}


def reply(mid, input=100, output=10, cached=0, thoughts=0, tool=0, model="gemini-3.5-flash"):
    tokens = {"input": input, "output": output, "cached": cached, "thoughts": thoughts, "tool": tool,
              "total": input + output + thoughts + tool}
    return {"id": mid, "timestamp": TS, "type": "gemini", "content": "a reply", "tokens": tokens, "model": model}


def question(mid):
    return {"id": mid, "timestamp": TS, "type": "user", "content": "a question"}


class TestHomes(unittest.TestCase):
    def test_gemini_cli_home_replaces_the_home_directory(self):
        self.assertEqual(gemini.default_homes({"GEMINI_CLI_HOME": "/h"}), ["/h/.gemini/tmp", "/h/.cache/.gemini/tmp"])

    def test_the_default_is_under_the_home_directory(self):
        self.assertEqual(gemini.default_homes({}), [os.path.expanduser(os.path.join("~", ".gemini", "tmp")),
                                                    os.path.expanduser(os.path.join("~", ".cache", ".gemini", "tmp"))])


class TestCounters(unittest.TestCase):
    def test_cached_tokens_come_out_of_the_prompt_and_thoughts_join_the_output(self):
        self.assertEqual(gemini.counters({"input": 100, "output": 10, "cached": 40, "thoughts": 5, "tool": 0, "total": 115}),
                         {"input": 60, "output": 15, "cache_read": 40, "cache_write": 0})

    def test_thoughts_already_inside_the_output_are_not_added_again(self):
        self.assertEqual(gemini.counters({"input": 100, "output": 10, "cached": 0, "thoughts": 5, "tool": 0, "total": 110})["output"], 10)

    def test_tool_prompt_tokens_join_the_input(self):
        beside = {"input": 100, "output": 10, "cached": 0, "thoughts": 5, "tool": 7, "total": 122}
        folded = dict(beside, total=117)
        self.assertEqual((gemini.counters(beside)["input"], gemini.counters(beside)["output"]), (107, 15))
        self.assertEqual((gemini.counters(folded)["input"], gemini.counters(folded)["output"]), (107, 10))

    def test_without_a_total_thoughts_are_added(self):
        self.assertEqual(gemini.counters({"input": 100, "output": 10, "thoughts": 5})["output"], 15)

    def test_a_count_that_is_not_a_number_is_zero(self):
        self.assertEqual(gemini.counters({"input": "many", "output": 10, "cached": None, "thoughts": True, "tool": 2.5}),
                         {"input": 0, "output": 10, "cache_read": 0, "cache_write": 0})

    def test_nothing_goes_below_zero(self):
        self.assertEqual(gemini.counters({"input": 10, "cached": 30, "output": -4}),
                         {"input": 0, "output": 0, "cache_read": 30, "cache_write": 0})


class TestRecordings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "agent-sample")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home")

    def scan(self, repo=None):
        return gemini.scan(repo or self.repo, gemini.default_homes({"GEMINI_CLI_HOME": self.home}))

    def test_every_recorded_day_and_model(self):
        agent_logs.install("gemini", os.path.join(self.home, ".gemini"), self.repo)
        result = self.scan()
        self.assertEqual(result.days, RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_a_rewound_and_rewritten_session_counts_each_reply_once(self):
        # 12 token-bearing writes of 7 replies, a checkpoint and a rewind.
        for path in agent_logs.install("gemini", os.path.join(self.home, ".gemini"), self.repo):
            if not path.endswith(REWIND):
                os.remove(path)
        day = self.scan().days["2026-06-12"]
        self.assertEqual((day["turns"], tu.source_total(day)), (7, 87_713))

    def test_the_sandbox_runtime_directory_is_read(self):
        agent_logs.install("gemini", os.path.join(self.home, ".cache", ".gemini"), self.repo)
        self.assertEqual(self.scan().days, RECORDED)

    def test_a_project_with_the_same_directory_name_elsewhere_is_not_matched(self):
        agent_logs.install("gemini", os.path.join(self.home, ".gemini"), self.repo)
        self.assertIsNone(self.scan(os.path.join(self.root, "elsewhere", "agent-sample")))

    def test_a_repository_reached_through_a_link_matches_either_path(self):
        link = os.path.join(self.root, "link")
        os.symlink(self.repo, link)
        agent_logs.install("gemini", os.path.join(self.home, ".gemini"), self.repo)
        self.assertEqual(self.scan(link).days, RECORDED)          # sessions hashed the real path
        other = os.path.join(self.root, "other-home")
        agent_logs.install("gemini", os.path.join(other, ".gemini"), link)
        self.assertEqual(gemini.scan(link, gemini.default_homes({"GEMINI_CLI_HOME": other})).days, RECORDED)

    def test_a_session_started_in_a_tracked_subdirectory_matches(self):
        fx._git(self.repo, "init", "-q", "-b", "main")
        fx._write(self.repo, "src/app/main.py", "print()\n")
        fx._git(self.repo, "add", ".")
        fx._git(self.repo, "commit", "-q", "-m", "Initial")
        agent_logs.install("gemini", os.path.join(self.home, ".gemini"), os.path.join(self.repo, "src", "app"))
        self.assertEqual(self.scan().days, RECORDED)

    def test_a_session_started_in_an_untracked_directory_does_not_match(self):
        fx._git(self.repo, "init", "-q", "-b", "main")
        fx._write(self.repo, "src/app/main.py", "print()\n")
        fx._git(self.repo, "add", ".")
        fx._git(self.repo, "commit", "-q", "-m", "Initial")
        agent_logs.install("gemini", os.path.join(self.home, ".gemini"), os.path.join(self.repo, "build"))
        self.assertIsNone(self.scan())

    def test_no_sessions_is_none(self):
        self.assertIsNone(self.scan())


class TestRules(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.makedirs(self.repo)
        self.home = os.path.join(tmp.name, "home")

    def write(self, name, recs, *sub, legacy=False):
        path = os.path.join(self.home, ".gemini", "tmp", "proj", "chats", *sub, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if legacy:
                json.dump(recs, f)
            else:
                f.write("\n".join(r if isinstance(r, str) else json.dumps(r) for r in recs) + "\n")

    def scan(self):
        return gemini.scan(self.repo, gemini.default_homes({"GEMINI_CLI_HOME": self.home}))

    def turns(self):
        return self.scan().days["2026-09-01"]["turns"]

    def test_tokens_written_after_the_reply_are_counted(self):
        first = dict(reply("m1"))
        del first["tokens"]
        self.write("s.jsonl", [meta(self.repo), first, reply("m1")])
        day = self.scan().days["2026-09-01"]
        self.assertEqual((day["turns"], tu.source_total(day)), (1, 110))

    def test_a_later_write_without_tokens_keeps_them(self):
        later = dict(reply("m1"))
        del later["tokens"]
        self.write("s.jsonl", [meta(self.repo), reply("m1"), later])
        self.assertEqual(self.turns(), 1)

    def test_checkpoint_messages_count_once(self):
        self.write("s.jsonl", [meta(self.repo), reply("m1"),
                               {"$set": {"messages": [question("u1"), reply("m1"), reply("m2")]}}])
        self.assertEqual(self.turns(), 2)

    def test_a_rewind_removes_nothing(self):
        self.write("s.jsonl", [meta(self.repo), reply("m1"), reply("m2"), {"$rewindTo": "m1"}, reply("m3")])
        self.assertEqual(self.turns(), 3)

    def test_a_legacy_session_is_read(self):
        self.write("s.json", dict(meta(self.repo), messages=[question("u1"), reply("m1"), reply("m2")]), legacy=True)
        self.assertEqual(self.turns(), 2)

    def test_a_legacy_session_and_its_migrated_copy_count_once(self):
        self.write("s.json", dict(meta(self.repo), messages=[reply("m1"), reply("m2")]), legacy=True)
        self.write("s.jsonl", [meta(self.repo), reply("m1"), reply("m2"), reply("m3")])
        self.assertEqual(self.turns(), 3)

    def test_a_legacy_session_of_another_project_is_not_read(self):
        self.write("s.json", dict(meta("/elsewhere"), messages=[reply("m1")]), legacy=True)
        self.assertIsNone(self.scan())

    def test_sub_agent_sessions_nested_under_their_parent_are_read(self):
        self.write("parent.jsonl", [meta(self.repo), reply("m1")])
        self.write("child.jsonl", [meta(self.repo, "s2", kind="subagent"), reply("m2")], "s1")
        self.assertEqual(self.turns(), 2)

    def test_a_reply_without_an_id_is_not_counted(self):
        # An id is what makes a rewritten message count once; an empty one
        # cannot, and would otherwise merge every such reply into one.
        self.write("s.jsonl", [meta(self.repo), reply("m1"), reply(""), dict(reply(""), tokens=dict(reply("")["tokens"], output=99))])
        day = self.scan().days["2026-09-01"]
        self.assertEqual((day["turns"], tu.source_total(day)), (1, 110))

    def test_only_replies_count(self):
        asked = dict(question("u1"), tokens={"input": 5, "output": 5})
        self.write("s.jsonl", [meta(self.repo), asked, reply("m1")])
        self.assertEqual(self.turns(), 1)

    def test_an_all_zero_reply_adds_no_turn(self):
        self.write("s.jsonl", [meta(self.repo), reply("m1", input=0, output=0)])
        self.assertEqual(self.scan().days, {})

    def test_unparseable_lines_are_counted(self):
        self.write("s.jsonl", [meta(self.repo), '{"tokens": BROKEN', reply("m1")])
        result = self.scan()
        self.assertEqual((result.malformed, result.days["2026-09-01"]["turns"]), (1, 1))

    def test_a_session_without_metadata_or_of_another_project_is_not_read(self):
        self.write("a.jsonl", [reply("m1")])
        self.write("b.jsonl", [meta("/elsewhere"), reply("m2")])
        self.assertIsNone(self.scan())

    @unittest.skipIf(os.geteuid() == 0, "root reads any directory")
    def test_an_unreadable_runtime_directory_is_counted_not_fatal(self):
        tmp = os.path.join(self.home, ".gemini", "tmp")
        os.makedirs(tmp)
        os.chmod(tmp, 0)
        self.addCleanup(os.chmod, tmp, 0o755)
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_unexpected_shapes_do_not_stop_the_scan(self):
        dated = dict(reply("m2"), timestamp=1756000000)
        listed = dict(reply("m3"), id=["m3"])
        worded = reply("m4")
        worded["tokens"] = dict(worded["tokens"], input="many")
        stamped = dict(reply("m6"), timestamp={"at": TS})
        modelled = dict(reply("m7"), model=["gemini-3.5-flash"])
        described = dict(reply("m8"), model={"name": "gemini-3.5-flash"})
        self.write("a.jsonl", [meta(self.repo), reply("m1"), dated, listed, worded, stamped, modelled, described])
        # A project hash that is not a string names no project.
        self.write("b.jsonl", [dict(meta(self.repo), projectHash=["not", "a", "hash"]), reply("m5")])
        self.write("c.json", dict(meta(self.repo), projectHash={"hash": "x"}, messages=[reply("m9")]), legacy=True)
        self.write("d.json", dict(meta(self.repo), messages=5), legacy=True)
        result = self.scan()
        day = result.days["2026-09-01"]
        # m1's 110 tokens, m4's 10 output tokens, and m7's and m8's 110 each
        # under an unknown model; d.json's messages cannot be read.
        self.assertEqual((day["turns"], tu.source_total(day), result.skipped), (4, 340, 1))
        self.assertEqual(sorted(day["models"]), ["gemini-3.5-flash", "unknown"])

    def test_files_outside_chats_are_ignored(self):
        path = os.path.join(self.home, ".gemini", "tmp", "proj", "logs.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(dict(meta(self.repo), messages=[reply("m1")]), f)
        self.write("notes.txt", [meta(self.repo), reply("m2")])
        self.assertIsNone(self.scan())


if __name__ == "__main__":
    unittest.main()
