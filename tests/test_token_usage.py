import json
import os
import tempfile
import types
import unittest

from clocwork import paths
from clocwork import sources as src
from clocwork import tokens as tu
from tests.test_sources import turn, write_transcripts


def entry(output, model="claude-opus-5"):
    """One source's record for one day."""
    return {"turns": 1, "models": {model: {"input": 0, "output": output, "cache_read": 0, "cache_write": 0}}}


class TestMerge(unittest.TestCase):
    def test_new_days_are_added(self):
        merged = tu.merge({"2026-08-06": {"claude-code": entry(10)}}, {"2026-08-07": {"claude-code": entry(20)}})
        self.assertEqual(sorted(merged), ["2026-08-06", "2026-08-07"])

    def test_a_larger_scan_replaces_the_archived_record(self):
        merged = tu.merge({"2026-08-06": {"claude-code": entry(10)}}, {"2026-08-06": {"claude-code": entry(50)}})
        self.assertEqual(tu.day_total(merged["2026-08-06"]), 50)

    def test_a_smaller_scan_never_shrinks_the_archive(self):
        # Logs expire, so a rescan of an old day reports less than was archived.
        merged = tu.merge({"2026-08-06": {"claude-code": entry(50)}}, {"2026-08-06": {"claude-code": entry(10)}})
        self.assertEqual(tu.day_total(merged["2026-08-06"]), 50)

    def test_days_absent_from_the_scan_survive(self):
        merged = tu.merge({"2026-07-01": {"claude-code": entry(99)}}, {"2026-08-06": {"claude-code": entry(1)}})
        self.assertEqual(tu.day_total(merged["2026-07-01"]), 99)

    def test_each_source_keeps_its_own_larger_record(self):
        # On one day Claude Code's logs have partly expired while Codex's have
        # grown. Comparing whole days (60 archived against 50 scanned) would
        # keep the stale Codex record and lose 20 tokens for good.
        archived = {"2026-08-06": {"claude-code": entry(50), "codex": entry(10)}}
        scanned = {"2026-08-06": {"claude-code": entry(20), "codex": entry(30)}}
        merged = tu.merge(archived, scanned)["2026-08-06"]
        self.assertEqual((tu.source_total(merged["claude-code"]), tu.source_total(merged["codex"])), (50, 30))

    def test_a_source_absent_from_the_scan_keeps_its_record(self):
        merged = tu.merge({"2026-08-06": {"claude-code": entry(5), "codex": entry(7)}},
                          {"2026-08-06": {"claude-code": entry(9)}})
        self.assertEqual(tu.source_total(merged["2026-08-06"]["codex"]), 7)

    def test_the_archive_passed_in_is_not_modified(self):
        archived = {"2026-08-06": {"claude-code": entry(5)}}
        tu.merge(archived, {"2026-08-06": {"codex": entry(7)}})
        self.assertEqual(archived, {"2026-08-06": {"claude-code": entry(5)}})


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
            days = {"2026-08-06": {"claude-code": {"turns": 2, "models": {"claude-opus-5": {
                "input": 1, "output": 2, "cache_read": 3, "cache_write": 4}}}}}
            tu.save(path, days)
            self.assertEqual(tu.load(path), days)
            with open(path) as f:
                self.assertEqual(json.load(f)["version"], 2)

    def test_archive_merges_a_scan_into_an_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            projects = os.path.join(d, "projects")
            repo = os.path.join(d, "Repo")
            write_transcripts(os.path.join(projects, paths.claude_project_dir(repo)),
                              {"a.jsonl": [turn("m1", "2026-08-06", output=7)]})
            path = os.path.join(d, "token_usage.json")
            tu.save(path, {"2026-07-01": {"claude-code": entry(5)}})
            days = tu.archive(repo, path, src.SOURCES, homes={"claude-code": [projects]}, log=lambda *a: None)
            self.assertEqual(sorted(days), ["2026-07-01", "2026-08-06"])
            self.assertEqual(tu.load(path), days)

    def test_archive_without_transcripts_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            existing = {"2026-07-01": {"claude-code": entry(5)}}
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

    def test_an_empty_home_override_reads_nothing_rather_than_the_defaults(self):
        seen = []
        source = types.SimpleNamespace(KEY="x", LABEL="X", default_homes=lambda env: ["/default"],
                                       scan=lambda repo, homes: seen.append(homes))
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], homes={"x": []}, log=lambda *a: None)
        self.assertEqual(seen, [[]])

    def test_a_source_that_finds_its_store_but_no_usage_still_writes_the_archive(self):
        empty = types.SimpleNamespace(KEY="empty", LABEL="Empty", default_homes=lambda env: [],
                                      scan=lambda repo, homes: tu.ScanResult({}, 0))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            self.assertEqual(tu.archive("/repo", path, [empty], log=lambda *a: None), {})
            self.assertTrue(os.path.exists(path))

    def write_raw(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def test_a_version_1_archive_is_read_as_claude_codes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            self.write_raw(path, {"version": 1, "days": {"2026-08-06": entry(5)}})
            self.assertEqual(tu.load(path), {"2026-08-06": {"claude-code": entry(5)}})

    def test_upgrading_a_version_1_archive_keeps_every_day_total(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            v1 = {"2026-08-06": entry(5), "2026-08-07": entry(11, model="claude-fable-5-1")}
            self.write_raw(path, {"version": 1, "days": v1})
            tu.save(path, tu.load(path))
            with open(path) as f:
                self.assertEqual(json.load(f)["version"], 2)
            self.assertEqual({date: tu.day_total(day) for date, day in tu.load(path).items()},
                             {"2026-08-06": 5, "2026-08-07": 11})

    def test_an_unknown_version_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            for data in ({"version": 99, "days": {}}, {"days": {}}):
                with self.subTest(data=data):
                    self.write_raw(path, data)
                    with self.assertRaises(tu.ArchiveError):
                        tu.load(path)

    def test_archive_files_each_scan_under_its_source(self):
        found = types.SimpleNamespace(KEY="found", LABEL="Found", default_homes=lambda env: [],
                                      scan=lambda repo, homes: tu.ScanResult({"2026-08-06": entry(4)}, 0))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            tu.save(path, {"2026-08-06": {"claude-code": entry(9)}})
            days = tu.archive("/repo", path, [found], log=lambda *a: None)
            self.assertEqual(days, {"2026-08-06": {"claude-code": entry(9), "found": entry(4)}})

    def test_a_failed_save_leaves_the_previous_archive_intact(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            original = {"2026-08-06": {"claude-code": entry(2)}}
            tu.save(path, original)
            # Attempt to save with an unserialisable value (will fail during json.dump)
            bad_data = {"2026-08-06": {"claude-code": {"turns": 1, "models": {"m": {"input": object()}}}}}
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
