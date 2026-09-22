import json
import os
import tempfile
import types
import unittest

from clocwork import paths
from clocwork import sources as src
from clocwork import tokens as tu
from clocwork import ui
from tests.test_sources import turn, write_transcripts
from tests.ui_recorder import Recorder


def entry(output, model="claude-opus-5"):
    """One source's record for one day."""
    return {"turns": 1, "models": {model: {"input": 0, "output": output, "cache_read": 0, "cache_write": 0}}}


def claude_only(projects):
    """Homes that point Claude Code at `projects` and every other agent at
    nothing, so the machine's own logs never reach a test."""
    return {s.KEY: [] for s in src.SOURCES} | {"claude-code": [projects]}


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
            days = tu.archive(repo, path, src.SOURCES, homes=claude_only(projects), report=ui.Reporter())
            self.assertEqual(sorted(days), ["2026-07-01", "2026-08-06"])
            self.assertEqual(tu.load(path), days)

    def test_archive_without_transcripts_leaves_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            existing = {"2026-07-01": {"claude-code": entry(5)}}
            tu.save(path, existing)
            before = os.stat(path).st_mtime_ns
            days = tu.archive(os.path.join(d, "Absent"), path, src.SOURCES,
                              homes=claude_only(os.path.join(d, "projects")), report=ui.Reporter())
            self.assertEqual(days, existing)
            self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_a_source_is_given_its_home_override_and_named_when_it_finds_nothing(self):
        seen, rec = [], Recorder()
        absent = types.SimpleNamespace(KEY="absent", LABEL="Absent Agent",
                                       default_homes=lambda env: ["/default"],
                                       scan=lambda repo, homes: seen.append(homes))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            tu.archive("/repo", path, [absent], homes={"absent": ["/override"]}, report=rec)
            self.assertFalse(os.path.exists(path))
        self.assertEqual(seen, [["/override"]])
        self.assertTrue(any("Absent Agent (/override)" in value for label, value in rec.of("detail")), rec.events)

    def test_an_empty_home_override_reads_nothing_rather_than_the_defaults(self):
        seen = []
        source = types.SimpleNamespace(KEY="x", LABEL="X", default_homes=lambda env: ["/default"],
                                       scan=lambda repo, homes: seen.append(homes))
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], homes={"x": []}, report=ui.Reporter())
        self.assertEqual(seen, [[]])

    def test_the_phase_result_names_each_source_and_the_archive_line_keeps_its_wording(self):
        found = types.SimpleNamespace(KEY="z", LABEL="Zed", default_homes=lambda env: [],
                                      scan=lambda repo, homes: tu.ScanResult(
                                          {"2026-01-01": {"turns": 1, "models": {"m": {
                                              "input": 7, "output": 3, "cache_read": 0, "cache_write": 0}}}}, 0))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [found], report=rec)
        # The daily token job greps this line and commits it: its wording is an interface.
        self.assertEqual(rec.of("done"), [("Zed 1 day", ("Archive now 1 days, 10 tokens (+1 days, +10 tokens)",))])
        self.assertIn(("scanned", "1 day of Zed logs"), rec.of("detail"))

    def test_nothing_found_is_said_in_one_line(self):
        absent = types.SimpleNamespace(KEY="a", LABEL="Absent", default_homes=lambda env: ["/x"],
                                       scan=lambda repo, homes: None)
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [absent], report=rec)
        self.assertEqual(rec.of("done"), [("no agent logs for this repository", ())])
        self.assertIn(("no logs", "Absent (/x)"), rec.of("detail"))
        self.assertIn(("archive", "unchanged: 0 days, 0 tokens"), rec.of("detail"))

    def test_a_source_that_finds_no_usage_leaves_the_archive_unwritten(self):
        empty = types.SimpleNamespace(KEY="empty", LABEL="Empty", default_homes=lambda env: [],
                                      scan=lambda repo, homes: tu.ScanResult({}, 0))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "token_usage.json")
            self.assertEqual(tu.archive("/repo", path, [empty], report=rec), {})
            self.assertFalse(os.path.exists(path))
        self.assertIn(("scanned", "0 days of Empty logs"), rec.of("detail"))

    def test_unreadable_files_are_counted_with_the_sources_reason(self):
        source = types.SimpleNamespace(KEY="z", LABEL="Zed", SKIPPED="compressed files need a newer Python",
                                       default_homes=lambda env: [],
                                       scan=lambda repo, homes: tu.ScanResult({}, 0, 3))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], report=rec)
            self.assertFalse(os.path.exists(os.path.join(d, "t.json")))
        self.assertIn("could not read 3 Zed files: compressed files need a newer Python", rec.of("warn"))

    def test_a_source_without_a_reason_still_has_its_unreadable_files_counted(self):
        source = types.SimpleNamespace(KEY="z", LABEL="Zed", default_homes=lambda env: [],
                                       scan=lambda repo, homes: tu.ScanResult({}, 0, 2))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], report=rec)
        self.assertIn("could not read 2 Zed files", rec.of("warn"))

    def test_sessions_a_source_held_back_are_counted_with_its_reason(self):
        source = types.SimpleNamespace(KEY="z", LABEL="Zed", HELD="their rows are missing",
                                       default_homes=lambda env: [],
                                       scan=lambda repo, homes: tu.ScanResult({}, 0, 0, 2))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], report=rec)
        self.assertIn("held back 2 Zed sessions: their rows are missing", rec.of("warn"))

    def test_one_held_session_is_singular(self):
        source = types.SimpleNamespace(KEY="z", LABEL="Zed", default_homes=lambda env: [],
                                       scan=lambda repo, homes: tu.ScanResult({}, 0, 0, 1))
        rec = Recorder()
        with tempfile.TemporaryDirectory() as d:
            tu.archive("/repo", os.path.join(d, "t.json"), [source], report=rec)
        self.assertIn("held back 1 Zed session", rec.of("warn"))

    def test_a_result_that_names_no_held_sessions_reports_none(self):
        self.assertEqual(tu.ScanResult({}, 0).held, 0)

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
            days = tu.archive("/repo", path, [found], report=ui.Reporter())
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

    def test_a_count_that_is_not_an_integer_is_zero(self):
        # No agent writes these; every reader gives them the same meaning.
        self.assertEqual(tu.additive("ten", 1.5, True, [3]), tu.empty_counts())
        self.assertEqual(tu.inclusive(prompt="100", output=5, cached=2.0, cache_write=None),
                         {"input": 0, "output": 5, "cache_read": 0, "cache_write": 0})
        self.assertEqual(tu.inclusive(prompt=100, output=5, cached=False)["input"], 100)

    def test_counters_never_go_negative(self):
        self.assertEqual(tu.inclusive(prompt=10, cached=40)["input"], 0)
        self.assertEqual(tu.additive(-3)["input"], 0)

    def test_text_is_a_non_empty_string_or_nothing(self):
        self.assertEqual(tu.text("r1"), "r1")
        for value in ("", None, 5, ["r1"], {"id": "r1"}):
            with self.subTest(value=value):
                self.assertIsNone(tu.text(value))

    def test_day_is_the_date_a_timestamp_starts_with_or_nothing(self):
        self.assertEqual(tu.day("2026-09-01T10:00:00.000Z"), "2026-09-01")
        self.assertEqual(tu.day("2026-09-01"), "2026-09-01")
        for value in ("", "yesterday", "2026-09", "09/01/2026", None, 1756000000, ["2026-09-01"], {"d": 1},
                      "\uff12\uff10\uff12\uff16-\uff10\uff19-\uff10\uff11T10:00:00Z", "\u0662\u0660\u0662\u0666-09-01"):
            with self.subTest(value=value):
                self.assertEqual(tu.day(value), "")

    def test_a_model_that_is_not_a_name_is_recorded_as_unknown(self):
        days = {}
        for model in (["gpt-5.5"], {"name": "gpt-5.5"}, 5, ""):
            tu.record(days, "2026-08-06", model, tu.additive(output=1))
        self.assertEqual(days["2026-08-06"]["models"], {"unknown": tu.additive(output=4)})

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
