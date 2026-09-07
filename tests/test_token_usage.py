import json
import os
import tempfile
import unittest

import token_usage as tu


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


class TestEncodeRepoPath(unittest.TestCase):
    def test_spaces_and_tildes_become_hyphens(self):
        self.assertEqual(
            tu.encode_repo_path("/Users/nick/Library/Mobile Documents/com~apple~CloudDocs/MyApp"),
            "-Users-nick-Library-Mobile-Documents-com-apple-CloudDocs-MyApp",
        )

    def test_leading_slash_becomes_a_hyphen(self):
        self.assertEqual(tu.encode_repo_path("/tmp/Repo"), "-tmp-Repo")


class TestTranscriptDir(unittest.TestCase):
    def test_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(tu.transcript_dir("/no/such/repo", projects_dir=d))

    def test_returns_directory_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            want = os.path.join(d, tu.encode_repo_path("/tmp/Repo"))
            os.makedirs(want)
            self.assertEqual(tu.transcript_dir("/tmp/Repo", projects_dir=d), want)


class TestScan(unittest.TestCase):
    def test_buckets_by_date_and_model(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                turn("m1", "2026-08-06"),
                turn("m2", "2026-08-06", model="claude-fable-5-1"),
                turn("m3", "2026-08-07"),
            ]})
            days = tu.scan(d).days
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
            days = tu.scan(d).days
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
            days = tu.scan(d).days
            self.assertEqual(days["2026-08-06"]["turns"], 1)

    def test_malformed_lines_are_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [
                '{"type":"assistant","message":{"usage":{ BROKEN',
                turn("m1", "2026-08-06"),
            ]})
            result = tu.scan(d)
            self.assertEqual(result.malformed, 1)
            self.assertEqual(result.days["2026-08-06"]["turns"], 1)

    def test_non_jsonl_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write_transcripts(d, {"a.jsonl": [turn("m1", "2026-08-06")]})
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write(turn("m2", "2026-08-06") + "\n")
            self.assertEqual(tu.scan(d).days["2026-08-06"]["turns"], 1)


if __name__ == "__main__":
    unittest.main()
