import json
import os
import tempfile
import unittest

from clocwork import agents, paths
from clocwork import sources as src
from clocwork.sources import claude_code as cc
from clocwork.sources import codex, copilot, gemini, kilo


def turn(msg_id, date, model="claude-opus-5", output=10, cache_read=1000):
    """One assistant record in the shape Claude Code writes."""
    return json.dumps({
        "type": "assistant",
        "timestamp": date + "T12:00:00.000Z",
        "uuid": msg_id + "-uuid",
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": 1,
                "output_tokens": output,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": 100,
            },
        },
    })


def write_transcripts(directory, files):
    os.makedirs(directory, exist_ok=True)
    for name, lines in files.items():
        with open(os.path.join(directory, name), "w") as f:
            f.write("\n".join(lines) + "\n")


class TestRegistry(unittest.TestCase):
    def test_every_claude_name_belongs_to_claude_code(self):
        for name in ("Claude Opus 4.6", "Claude Opus 5 (1M)", "Claude Sonnet 3.5", agents.UNKNOWN_CLAUDE):
            with self.subTest(name=name):
                self.assertIs(src.source_for(name), cc)

    def test_codex_commits_belong_to_the_codex_reader(self):
        self.assertIs(src.source_for("Codex"), codex)

    def test_gemini_commits_belong_to_the_gemini_reader(self):
        self.assertIs(src.source_for("Gemini"), gemini)

    def test_copilot_commits_belong_to_the_copilot_reader(self):
        self.assertIs(src.source_for("Copilot"), copilot)

    def test_kilo_code_commits_belong_to_the_kilo_reader(self):
        # The fork and its parent must not claim each other: a Kilo commit's
        # tokens come from the kilo store and an OpenCode one's from the
        # opencode store, and no commit may carry both.
        self.assertIs(src.source_for("Kilo Code"), kilo)
        self.assertIsNot(src.source_for("OpenCode"), kilo)

    def test_antigravity_s_trailers_carry_its_tokens(self):
        self.assertIs(src.source_for("Antigravity"), src.by_key("antigravity"))
        self.assertIsNot(src.source_for("Gemini"), src.by_key("antigravity"))

    def test_agents_without_a_reader_belong_to_no_source(self):
        for name in ["Cursor", "Devin", "aider", "Gemini Code Assist",
                     "OpenCode GitHub agent", "Misc", "", None]:
            with self.subTest(name=name):
                self.assertIsNone(src.source_for(name))

    def test_no_agent_name_matches_two_sources(self):
        names = [n for _needle, n in agents.VENDORS] + [
            "Claude Opus 4.6", "Claude Opus 5 (1M)", "Claude Sonnet 3.5", agents.UNKNOWN_CLAUDE,
            "Codex Cloud", "Gemini Code Assist"]
        for name in names:
            with self.subTest(name=name):
                self.assertLessEqual(sum(1 for s in src.SOURCES if s.AGENT.search(name)), 1)

    def test_by_key(self):
        self.assertIs(src.by_key("claude-code"), cc)
        self.assertIs(src.by_key("codex"), codex)
        self.assertIs(src.by_key("gemini"), gemini)
        self.assertIs(src.by_key("copilot"), copilot)
        self.assertIs(src.by_key("kilo"), kilo)
        self.assertIsNone(src.by_key("an-agent-from-the-future"))


class TestTranscriptDir(unittest.TestCase):
    def test_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(cc.transcript_dir("/no/such/repo", d))

    def test_returns_directory_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            want = os.path.join(d, paths.claude_project_dir("/tmp/Repo"))
            os.makedirs(want)
            self.assertEqual(cc.transcript_dir("/tmp/Repo", d), want)


class TestClaudeCodeScan(unittest.TestCase):
    def test_no_transcripts_in_any_home_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(cc.scan("/no/such/repo", [d]))

    def test_the_repository_directory_is_found_under_a_home(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(os.path.join(d, paths.claude_project_dir("/tmp/Repo")),
                              {"a.jsonl": [turn("m1", "2026-08-06")]})
            result = cc.scan("/tmp/Repo", [os.path.join(d, "absent"), d])
            self.assertEqual(result.days["2026-08-06"]["turns"], 1)
            self.assertEqual(result.skipped, 0)

    def test_buckets_by_date_and_model(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                turn("m1", "2026-08-06"),
                turn("m2", "2026-08-06", model="claude-fable-5-1"),
                turn("m3", "2026-08-07"),
            ]})
            days = cc.scan_directory(d).days
            self.assertEqual(sorted(days), ["2026-08-06", "2026-08-07"])
            self.assertEqual(days["2026-08-06"]["turns"], 2)
            self.assertEqual(sorted(days["2026-08-06"]["models"]), ["claude-fable-5-1", "claude-opus-5"])
            self.assertEqual(days["2026-08-06"]["models"]["claude-opus-5"],
                             {"input": 1, "output": 10, "cache_read": 1000, "cache_write": 100})

    def test_replayed_message_ids_are_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {
                "a.jsonl": [turn("m1", "2026-08-06"), turn("m2", "2026-08-06")],
                "b.jsonl": [turn("m1", "2026-08-06"), turn("m3", "2026-08-06")],
            })
            days = cc.scan_directory(d).days
            self.assertEqual(days["2026-08-06"]["turns"], 3)
            self.assertEqual(days["2026-08-06"]["models"]["claude-opus-5"]["output"], 30)

    def test_non_assistant_and_usageless_records_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                json.dumps({"type": "user", "timestamp": "2026-08-06T12:00:00Z", "message": {"id": "u1"}}),
                json.dumps({"type": "assistant", "timestamp": "2026-08-06T12:00:00Z",
                            "message": {"id": "m9", "model": "claude-opus-5"}}),
                turn("m1", "2026-08-06"),
            ]})
            self.assertEqual(cc.scan_directory(d).days["2026-08-06"]["turns"], 1)

    def test_a_turn_that_used_no_tokens_adds_nothing(self):
        silent = json.loads(turn("m2", "2026-08-06", model="<synthetic>", output=0, cache_read=0))
        silent["message"]["usage"].update(input_tokens=0, cache_creation_input_tokens=0)
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [json.dumps(dict(silent, timestamp="2026-08-05T12:00:00.000Z")),
                                              turn("m1", "2026-08-06"), json.dumps(silent)]})
            days = cc.scan_directory(d).days
        self.assertEqual(sorted(days), ["2026-08-06"])
        self.assertEqual((days["2026-08-06"]["turns"], sorted(days["2026-08-06"]["models"])), (1, ["claude-opus-5"]))

    def test_malformed_lines_are_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                '{"type":"assistant","message":{"usage":{ BROKEN',
                turn("m1", "2026-08-06"),
            ]})
            result = cc.scan_directory(d)
            self.assertEqual(result.malformed, 1)
            self.assertEqual(result.days["2026-08-06"]["turns"], 1)

    def test_a_count_that_is_not_an_integer_reads_as_zero(self):
        rec = json.loads(turn("m1", "2026-08-06"))
        rec["message"]["usage"].update(input_tokens="1", cache_creation_input_tokens=100.5)
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [json.dumps(rec)]})
            self.assertEqual(cc.scan_directory(d).days["2026-08-06"]["models"]["claude-opus-5"],
                             {"input": 0, "output": 10, "cache_read": 1000, "cache_write": 0})

    def test_records_of_the_wrong_shape_are_skipped_not_fatal(self):
        def odd(**changes):
            rec = json.loads(turn(changes.pop("msg_id"), "2026-08-06"))
            for path, value in changes.items():
                *parents, leaf = path.split("__")
                target = rec
                for p in parents:
                    target = target[p]
                target[leaf] = value
            return json.dumps(rec)
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                json.dumps(["usage"]),
                json.dumps({"type": "assistant", "message": "usage"}),
                odd(msg_id="m9", message__usage=["input_tokens"]),
                turn("m1", "2026-08-06"),
                odd(msg_id="m2", message__id=["m2"]),               # no message id: the uuid stands in,
                odd(msg_id="m2", message__id={"id": "m2"}),         # so its replay counts once
                odd(msg_id="m3", timestamp={"at": "2026-08-06"}),   # on no day
                odd(msg_id="m4", message__model=["claude-opus-5"]),
            ]})
            result = cc.scan_directory(d)
        self.assertEqual(result.malformed, 0)
        day = result.days["2026-08-06"]
        self.assertEqual((day["turns"], {m: c["output"] for m, c in day["models"].items()}),
                         (3, {"claude-opus-5": 20, "unknown": 10}))

    def test_non_jsonl_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [turn("m1", "2026-08-06")]})
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write(turn("m2", "2026-08-06") + "\n")
            self.assertEqual(cc.scan_directory(d).days["2026-08-06"]["turns"], 1)


if __name__ == "__main__":
    unittest.main()
