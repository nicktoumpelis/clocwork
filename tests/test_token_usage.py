import json
import os
import tempfile
import types
import unittest

from clocwork import paths
from clocwork import sources as src
from clocwork import tokens as tu
from tests.test_sources import turn, write_transcripts


class TestMerge(unittest.TestCase):
    def day(self, output):
        return {"turns": 1, "models": {"claude-opus-5": {"input": 0, "output": output,
                                                         "cache_read": 0, "cache_write": 0}}}

    def test_new_days_are_added(self):
        merged = tu.merge({"2026-08-06": self.day(10)}, {"2026-08-07": self.day(20)})
        self.assertEqual(sorted(merged), ["2026-08-06", "2026-08-07"])

    def test_a_larger_scan_replaces_the_archived_day(self):
        merged = tu.merge({"2026-08-06": self.day(10)}, {"2026-08-06": self.day(50)})
        self.assertEqual(tu.day_total(merged["2026-08-06"]), 50)

    def test_a_smaller_scan_never_shrinks_the_archive(self):
        # Transcripts expire, so a rescan of an old day reports less than was
        # archived. The archive must win.
        merged = tu.merge({"2026-08-06": self.day(50)}, {"2026-08-06": self.day(10)})
        self.assertEqual(tu.day_total(merged["2026-08-06"]), 50)

    def test_days_absent_from_the_scan_survive(self):
        merged = tu.merge({"2026-07-01": self.day(99)}, {"2026-08-06": self.day(1)})
        self.assertEqual(tu.day_total(merged["2026-07-01"]), 99)


class TestArchiveRoundTrip(unittest.TestCase):
    def test_load_of_a_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(tu.load(os.path.join(d, "nope.json")), {})

    def test_save_leaves_a_readable_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.json")
            tu.save(p, {})
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o644)

    def test_save_then_load_preserves_days(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            days = {"2026-08-06": {"turns": 2, "models": {"claude-opus-5": {
                "input": 1, "output": 2, "cache_read": 3, "cache_write": 4}}}}
            tu.save(path, days)
            self.assertEqual(tu.load(path), days)
            with open(path) as f:
                self.assertEqual(json.load(f)["version"], tu.VERSION)

    def test_archive_merges_a_scan_into_an_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            projects = os.path.join(d, "projects")
            repo = os.path.join(d, "Repo")
            write_transcripts(os.path.join(projects, paths.claude_project_dir(repo)),
                              {"a.jsonl": [turn("m1", "2026-08-06", output=7)]})
            path = os.path.join(d, "token_usage.json")
            tu.save(path, {"2026-07-01": {"turns": 1, "models": {"claude-opus-5": {
                "input": 0, "output": 5, "cache_read": 0, "cache_write": 0}}}})
            days = tu.archive(repo, path, src.SOURCES, homes={"claude-code": [projects]}, log=lambda *a: None)
            self.assertEqual(sorted(days), ["2026-07-01", "2026-08-06"])
            self.assertEqual(tu.load(path), days)

    def test_archive_without_transcripts_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            existing = {"2026-07-01": {"turns": 1, "models": {"claude-opus-5": {
                "input": 0, "output": 5, "cache_read": 0, "cache_write": 0}}}}
            tu.save(path, existing)
            before = os.stat(path).st_mtime_ns
            days = tu.archive(os.path.join(d, "Absent"), path, src.SOURCES,
                              homes={"claude-code": [os.path.join(d, "projects")]}, log=lambda *a: None)
            self.assertEqual(days, existing)
            self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_a_source_is_given_its_home_override_and_named_when_it_finds_nothing(self):
        seen, lines = [], []
        absent = types.SimpleNamespace(KEY="absent", LABEL="Absent Agent",
                                       default_homes=lambda env: ["/default"],
                                       scan=lambda repo, homes: seen.append(homes))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            tu.archive("/repo", path, [absent], homes={"absent": ["/override"]}, log=lines.append)
            self.assertFalse(os.path.exists(path))
        self.assertEqual(seen, [["/override"]])
        self.assertTrue(any("Absent Agent (/override)" in line for line in lines), lines)

    def test_a_source_that_finds_its_store_but_no_usage_still_writes_the_archive(self):
        empty = types.SimpleNamespace(KEY="empty", LABEL="Empty", default_homes=lambda env: [],
                                      scan=lambda repo, homes: tu.ScanResult({}, 0))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            self.assertEqual(tu.archive("/repo", path, [empty], log=lambda *a: None), {})
            self.assertTrue(os.path.exists(path))

    def test_a_failed_save_leaves_the_previous_archive_intact(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            original = {"2026-08-06": {"turns": 2, "models": {"claude-opus-5": {
                "input": 1, "output": 2, "cache_read": 3, "cache_write": 4}}}}
            tu.save(path, original)
            # Attempt to save with an unserialisable value (will fail during json.dump)
            bad_data = {"2026-08-06": {"turns": 1, "models": {"m": {"input": object()}}}}
            with self.assertRaises(TypeError):
                tu.save(path, bad_data)
            # Verify the original file is still intact
            self.assertEqual(tu.load(path), original)


class TestCounters(unittest.TestCase):
    """Every reader reduces its provider's fields to four disjoint counters."""

    def test_additive_takes_counters_as_reported(self):
        self.assertEqual(tu.additive(1, 2, 3, 4),
                         {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4})

    def test_additive_treats_missing_values_as_zero(self):
        self.assertEqual(tu.additive(None, 5),
                         {"input": 0, "output": 5, "cache_read": 0, "cache_write": 0})

    def test_inclusive_takes_cached_and_written_tokens_out_of_the_prompt(self):
        # An OpenAI-style prompt of 1,000 tokens, 700 read from cache and 200 written to it.
        self.assertEqual(tu.inclusive(prompt=1000, output=50, cached=700, cache_write=200),
                         {"input": 100, "output": 50, "cache_read": 700, "cache_write": 200})

    def test_an_inclusive_reading_sums_to_the_prompt_plus_the_output(self):
        # Summing the four counters must not count a cached token twice.
        self.assertEqual(sum(tu.inclusive(prompt=1000, output=50, cached=700, cache_write=200).values()), 1050)

    def test_counters_never_go_negative(self):
        self.assertEqual(tu.inclusive(prompt=10, cached=40)["input"], 0)
        self.assertEqual(tu.additive(-3)["input"], 0)

    def test_record_adds_a_turn_and_its_counters(self):
        days = {}
        tu.record(days, "2026-08-06", "m", tu.additive(1, 2, 3, 4))
        tu.record(days, "2026-08-06", "m", tu.additive(1, 2, 3, 4))
        tu.record(days, "2026-08-06", None, tu.additive(output=9))
        self.assertEqual(days["2026-08-06"]["turns"], 3)
        self.assertEqual(days["2026-08-06"]["models"]["m"],
                         {"input": 2, "output": 4, "cache_read": 6, "cache_write": 8})
        self.assertEqual(days["2026-08-06"]["models"]["unknown"]["output"], 9)


if __name__ == "__main__":
    unittest.main()
