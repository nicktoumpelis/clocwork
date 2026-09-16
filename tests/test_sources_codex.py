import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from clocwork import tokens as tu
from clocwork.sources import codex
from tests import agent_logs
from tests import repo_fixture as fx

# What the recordings hold, computed before reduction and without the
# reader: each 0.130-0.149 session's final running total, and the sum of each
# 0.153.4 response's own usage. Input is uncached input.
RECORDED = {
    "2026-05-23": {"turns": 3, "models": {
        "gpt-5.5": {"input": 50_241, "output": 10, "cache_read": 13_056, "cache_write": 0},
        "gpt-5.3-codex": {"input": 8_597, "output": 19, "cache_read": 19_840, "cache_write": 0}}},
    "2026-05-29": {"turns": 3, "models": {
        "gpt-5.5": {"input": 49_692, "output": 15, "cache_read": 38_016, "cache_write": 0}}},
    "2026-08-26": {"turns": 35, "models": {
        "gpt-5.6-terra": {"input": 102_285, "output": 5_175, "cache_read": 601_344, "cache_write": 0}}},
    "2026-09-07": {"turns": 53, "models": {
        "gpt-5.6-terra": {"input": 83_900, "output": 11_116, "cache_read": 883_456, "cache_write": 0}}},
}
TS = "2026-09-01T10:00:00.000Z"
try:
    GIT_VERSION = tuple(int(n) for n in subprocess.run(["git", "version"], capture_output=True, text=True)
                        .stdout.split()[2].split(".")[:2])
except (OSError, IndexError, ValueError):
    GIT_VERSION = ()                # no git, or a version line this cannot read
GIT_NO_LAZY_FETCH = GIT_VERSION >= (2, 44)


def git_repo(path, remote=None):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    if remote:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", remote], check=True)
    return path


def meta(sid, cwd, forked_from=None, git=None):
    payload = {"id": sid, "forked_from_id": forked_from, "cwd": cwd, "source": "cli"}
    if git is not None:
        payload["git"] = git
    return {"timestamp": TS, "type": "session_meta", "payload": payload}


def turn(turn_id, model):
    return {"timestamp": TS, "type": "turn_context", "payload": {"turn_id": turn_id, "model": model}}


def usage(input, cached, output, cache_write=0):
    return {"input_tokens": input, "cached_input_tokens": cached, "cache_write_input_tokens": cache_write,
            "output_tokens": output, "reasoning_output_tokens": 0, "total_tokens": input + output}


def plus(a, b):
    return {k: a[k] + b[k] for k in a}


def record(response_id, turn_id, u):
    return {"timestamp": TS, "type": "token_usage_record",
            "payload": {"response_id": response_id, "turn_id": turn_id, "usage": u}}


def count(total, last):
    return {"timestamp": TS, "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": total, "last_token_usage": last}}}


class TestHomes(unittest.TestCase):
    def test_codex_home_moves_both_directories(self):
        self.assertEqual(codex.default_homes({"CODEX_HOME": "/x"}), ["/x/sessions", "/x/archived_sessions"])

    def test_the_default_is_dot_codex(self):
        homes = codex.default_homes({})
        self.assertEqual([h.split(os.sep)[-2:] for h in homes], [[".codex", "sessions"], [".codex", "archived_sessions"]])


class TestRecordings(unittest.TestCase):
    """The reader over real sessions."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "agent-sample")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "codex")

    def scan(self, repo=None):
        return codex.scan(repo or self.repo, codex.default_homes({"CODEX_HOME": self.home}))

    def test_every_recorded_day_and_model(self):
        agent_logs.install("codex", self.home, self.repo)
        result = self.scan()
        self.assertEqual(result.days, RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_a_forks_copy_of_its_parents_usage_counts_once(self):
        agent_logs.install("codex", self.home, self.repo)
        # 29,223 + 29,241 by the parent and 29,259 by the fork; summing every
        # event in both files would give 146,187.
        self.assertEqual(tu.source_total(self.scan().days["2026-05-29"]), 87_723)

    def test_a_fork_whose_parent_is_gone_counts_only_its_own_usage(self):
        for path in agent_logs.install("codex", self.home, self.repo):
            if path.endswith("-019e7583-0b33-7912-a209-4c0407cfa243.jsonl"):
                os.remove(path)
        # The parent's 58,464 went with its file; the fork's copy of them is
        # recognised by its turns, which began before the fork did.
        day = self.scan().days["2026-05-29"]
        self.assertEqual((day["turns"], tu.source_total(day)), (1, 29_259))

    def test_sub_agents_whose_parent_is_gone_keep_their_own_usage(self):
        for path in agent_logs.install("codex", self.home, self.repo):
            if path.endswith("-01a03eb1-6b82-78e3-87e0-2578e88e80cf.jsonl"):
                os.remove(path)
        # 708,804 less the parent's 392,189 over 18 responses.
        day = self.scan().days["2026-08-26"]
        self.assertEqual((day["turns"], tu.source_total(day)), (17, 316_615))

    def test_archived_sessions_are_read(self):
        agent_logs.install("codex", self.home, self.repo)
        shutil.rmtree(os.path.join(self.home, "sessions"))
        self.assertEqual(self.scan().days, {"2026-05-23": {"turns": 1, "models": {
            "gpt-5.5": {"input": 23_728, "output": 5, "cache_read": 6_528, "cache_write": 0}}}})

    def test_a_session_naming_the_same_remote_matches_from_any_clone(self):
        # Installed for a path the clone is not at: only sessions that name
        # the remote (the Irrlicht ones) can match it.
        agent_logs.install("codex", self.home, os.path.join(self.root, "elsewhere"))
        clone = git_repo(os.path.join(self.root, "clone"), "git@github.com:example/agent-sample.git")
        self.assertEqual(sorted(self.scan(clone).days), ["2026-05-23", "2026-05-29"])

    def test_a_session_naming_another_remote_does_not_match_by_path(self):
        agent_logs.install("codex", self.home, self.repo)
        git_repo(self.repo, "https://github.com/example/other.git")
        # The zoetrope sessions name no remote and still match by path.
        self.assertEqual(sorted(self.scan().days), ["2026-08-26", "2026-09-07"])

    def test_sessions_in_a_subdirectory_match(self):
        agent_logs.install("codex", self.home, os.path.join(self.repo, "pkg"))
        self.assertEqual(self.scan().days, RECORDED)

    def test_a_sibling_whose_name_extends_the_repositorys_does_not_match(self):
        agent_logs.install("codex", self.home, self.repo + "-stats")
        self.assertIsNone(self.scan())

    def test_no_rollouts_is_none(self):
        self.assertIsNone(self.scan())


class TestRules(unittest.TestCase):
    """The reader's rules, each on a small synthetic rollout."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = os.path.join(os.path.realpath(tmp.name), "repo")
        os.makedirs(self.repo)
        self.home = os.path.join(tmp.name, "codex")

    def write(self, name, lines, opener=open, where=("sessions", "2026", "09", "01")):
        path = os.path.join(self.home, *where, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with opener(path, "wt", encoding="utf-8") as f:
            f.write("\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n")

    def scan(self):
        return codex.scan(self.repo, codex.default_homes({"CODEX_HOME": self.home}))

    def day(self):
        return self.scan().days["2026-09-01"]

    NEW = "git@github.com:me/new-name.git"
    OLD = "https://github.com/me/old-name.git"

    def committed(self, remote):
        """Make the repository a clone of `remote` with one commit, and return its hash."""
        git_repo(self.repo, remote)
        fx._git(self.repo, "commit", "-q", "--allow-empty", "-m", "Start")
        return fx._git(self.repo, "rev-parse", "HEAD")

    def session(self, name, cwd, git):
        self.write(name, [meta(name, cwd, git=git), turn("t1", "gpt-5.5"), record(name, "t1", usage(10, 0, 1))])

    def test_a_session_recorded_before_a_rename_matches_by_its_commit(self):
        head = self.committed(self.NEW)
        self.session("rollout-a.jsonl", self.repo, {"repository_url": self.OLD, "commit_hash": head})
        self.session("rollout-b.jsonl", os.path.join(self.repo, "pkg"), {"repository_url": self.OLD, "commit_hash": head.upper()})
        self.assertEqual(self.day()["turns"], 2)

    def test_another_remotes_session_in_the_directory_needs_one_of_its_commits(self):
        head = self.committed(self.NEW)
        other = "https://github.com/someone/else.git"
        self.session("rollout-a.jsonl", self.repo, {"repository_url": other, "commit_hash": "0" * 40})
        self.session("rollout-b.jsonl", self.repo, {"repository_url": other})
        self.session("rollout-c.jsonl", self.repo, {"repository_url": other, "commit_hash": head[:12]})
        self.session("rollout-d.jsonl", self.repo, {"repository_url": other, "commit_hash": ["not", "a", "hash"]})
        self.session("rollout-e.jsonl", self.repo + "-copy", {"repository_url": other, "commit_hash": head})
        tree = fx._git(self.repo, "rev-parse", "HEAD^{tree}")
        self.session("rollout-f.jsonl", self.repo, {"repository_url": other, "commit_hash": tree})
        self.assertIsNone(self.scan())

    def test_git_is_asked_once_per_commit_and_only_for_sessions_in_the_directory(self):
        head = self.committed(self.NEW)
        old = {"repository_url": self.OLD, "commit_hash": head}
        self.session("rollout-a.jsonl", self.repo, old)
        self.session("rollout-b.jsonl", self.repo, old)
        self.session("rollout-c.jsonl", "/elsewhere", dict(old, commit_hash="1" * 40))
        self.session("rollout-d.jsonl", self.repo, {"repository_url": self.NEW, "commit_hash": "2" * 40})
        self.session("rollout-e.jsonl", self.repo, dict(old, commit_hash="--help"))
        with mock.patch.object(subprocess, "run", wraps=subprocess.run) as run:
            self.assertEqual(self.day()["turns"], 3)
        asked = [c for c in run.call_args_list if "cat-file" in c.args[0]]
        self.assertEqual([c.args[0] for c in asked], [["git", "-C", self.repo, "cat-file", "-e", head + "^{commit}"]])
        # Never a fetch or a prompt: no lazy fetch (git 2.44+), no transport
        # at all whatever the user's config allows (older git), no terminal
        # input, and git told not to ask.
        env = asked[0].kwargs["env"]
        self.assertEqual((env["GIT_NO_LAZY_FETCH"], env["GIT_ALLOW_PROTOCOL"], env["GIT_TERMINAL_PROMPT"]), ("1", "", "0"))
        self.assertIs(asked[0].kwargs["stdin"], subprocess.DEVNULL)

    @unittest.skipUnless(GIT_NO_LAZY_FETCH, "GIT_NO_LAZY_FETCH arrived in git 2.44")
    def test_an_unknown_commit_in_a_partial_clone_is_not_fetched(self):
        # The case the lookup exists for, another repository's hash, is the
        # one a partial clone would otherwise try to fetch from its remote.
        upstream = os.path.join(os.path.dirname(self.repo), "upstream")
        git_repo(upstream)
        fx._git(upstream, "commit", "-q", "--allow-empty", "-m", "Start")
        fx._git(upstream, "config", "uploadpack.allowFilter", "true")
        os.rmdir(self.repo)
        # The objects come from a local promisor remote; origin only names the repository.
        fx._git(os.path.dirname(self.repo), "clone", "-q", "-o", "upstream", "--filter=blob:none",
                "file://" + upstream, self.repo)
        fx._git(self.repo, "remote", "add", "origin", self.NEW)
        self.session("rollout-a.jsonl", self.repo, {"repository_url": self.OLD, "commit_hash": "1" * 40})
        trace = os.path.join(os.path.dirname(self.repo), "trace")
        with mock.patch.dict(os.environ, {"GIT_TRACE": trace}):
            self.assertIsNone(self.scan())
        with open(trace) as f:
            fetches = [line for line in f if "built-in: git fetch" in line]
        self.assertEqual(fetches, [])

    def test_the_prompt_count_includes_cached_and_written_tokens(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.6-sol"),
                                       record("r1", "t1", usage(100, 30, 5, cache_write=20))])
        self.assertEqual(self.day()["models"]["gpt-5.6-sol"],
                         {"input": 50, "output": 5, "cache_read": 30, "cache_write": 20})

    def test_a_response_written_in_both_formats_counts_once(self):
        # CLI 0.153.4 writes each response's record, then its token_count.
        u = usage(100, 40, 10)
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.6-sol"), record("r1", "t1", u), count(u, u)])
        self.assertEqual(self.day(), {"turns": 1, "models": {
            "gpt-5.6-sol": {"input": 60, "output": 10, "cache_read": 40, "cache_write": 0}}})

    def test_a_session_resumed_after_the_upgrade_keeps_its_earlier_usage(self):
        # Resuming appends to the same rollout: token_count events written by
        # the older CLI, then records written by the newer one.
        u1, u2, u3 = usage(100, 0, 1), usage(200, 0, 2), usage(300, 0, 3)
        t2 = plus(u1, u2)
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"), count(u1, u1), count(t2, u2),
                                       turn("t2", "gpt-5.5"), record("r1", "t2", u3), count(plus(t2, u3), u3)])
        self.assertEqual((self.day()["turns"], tu.source_total(self.day())), (3, 606))

    def test_a_response_recorded_in_two_files_counts_once(self):
        for name in ("rollout-a.jsonl", "rollout-b.jsonl"):
            self.write(name, [meta(name, self.repo), turn("t1", "gpt-5.6-sol"), record("r1", "t1", usage(100, 0, 10))])
        self.assertEqual(self.day()["turns"], 1)

    def test_unrelated_sessions_that_report_the_same_usage_both_count(self):
        # Irrlicht's 2-12, 5-1 and 5-2 recordings all open with this response.
        first = usage(30_256, 6_528, 5)
        for name in ("rollout-a.jsonl", "rollout-b.jsonl"):
            self.write(name, [meta(name, self.repo), turn("t1", "gpt-5.5"), count(first, first)])
        self.assertEqual((self.day()["turns"], tu.source_total(self.day())), (2, 60_522))

    def test_a_fork_of_a_fork_drops_everything_it_inherited(self):
        u1, u2, u3 = usage(100, 0, 1), usage(200, 0, 2), usage(300, 0, 3)
        t2 = plus(u1, u2)
        t3 = plus(t2, u3)
        self.write("rollout-1.jsonl", [meta("p", self.repo), turn("t", "gpt-5.5"), count(u1, u1)])
        self.write("rollout-2.jsonl", [meta("f", self.repo, forked_from="p"), meta("p", self.repo),
                                       turn("t", "gpt-5.5"), count(u1, u1), count(t2, u2)])
        self.write("rollout-3.jsonl", [meta("g", self.repo, forked_from="f"), meta("f", self.repo, forked_from="p"),
                                       turn("t", "gpt-5.5"), count(u1, u1), count(t2, u2), count(t3, u3)])
        # 101 + 202 + 303; every event in every file would be 1,010.
        self.assertEqual((self.day()["turns"], tu.source_total(self.day())), (3, 606))

    def test_a_fork_whose_parent_cannot_be_read_counts_only_its_own_usage(self):
        # Codex ids are UUIDv7, ordered by creation time: the parent's turns,
        # copied into the fork, began before the fork's own id was made.
        parent, fork = "019e0000-0000-7000-8000-000000000001", "019e0000-0000-7000-8000-000000000005"
        u1, u2 = usage(100, 0, 1), usage(200, 0, 2)
        self.write("rollout-1.jsonl.zst", ["compressed, unreadable here"])
        self.write("rollout-2.jsonl", [meta(fork, self.repo, forked_from=parent), meta(parent, self.repo),
                                       turn("019e0000-0000-7000-8000-000000000002", "gpt-5.5"), count(u1, u1),
                                       turn("019e0000-0000-7000-8000-000000000009", "gpt-5.5"), count(plus(u1, u2), u2)])
        with mock.patch.object(codex, "zstd", None):
            result = self.scan()
        day = result.days["2026-09-01"]
        self.assertEqual((day["turns"], tu.source_total(day), result.skipped), (1, 202, 1))

    def test_a_session_kept_in_two_places_counts_once(self):
        u = usage(100, 0, 1)
        lines = [meta("a", self.repo), turn("t", "gpt-5.5"), count(u, u)]
        self.write("rollout-a.jsonl", lines)
        self.write("rollout-a.jsonl", lines, where=("archived_sessions",))
        self.assertEqual(self.day()["turns"], 1)

    def test_events_without_new_usage_add_nothing(self):
        u = usage(100, 0, 1)
        self.write("rollout-a.jsonl", [
            meta("a", self.repo), turn("t", "gpt-5.5"),
            {"timestamp": TS, "type": "event_msg", "payload": {"type": "token_count", "info": None}},
            count(u, u), count(u, u),
            count(u, usage(0, 0, 0)),          # the same total again, as after a compaction
        ])
        self.assertEqual(self.day()["turns"], 1)

    def test_an_all_zero_record_adds_no_turn(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"),
                                       record("r1", "t1", usage(0, 0, 0)), record("r2", "t1", usage(10, 0, 1))])
        self.assertEqual(self.day()["turns"], 1)

    def test_a_compaction_snapshot_adds_nothing(self):
        self.write("rollout-a.jsonl", [
            meta("a", self.repo), turn("t1", "gpt-5.5"), record("r1", "t1", usage(100, 0, 1)),
            {"timestamp": TS, "type": "compacted", "payload": {"latest_token_usage_record": {
                "response_id": "r9", "turn_id": "t1", "usage": usage(5_000, 0, 50)}}},
        ])
        self.assertEqual(tu.source_total(self.day()), 101)

    def test_the_model_comes_from_the_turn_else_the_latest_turn_else_unknown(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), record("r0", "t0", usage(10, 0, 1)),
                                       turn("t1", "gpt-5.3-codex"), turn("t2", "gpt-5.5"),
                                       record("r1", "t1", usage(10, 0, 1)), record("r2", "t9", usage(10, 0, 1))])
        models = self.day()["models"]
        self.assertEqual({m: c["input"] for m, c in models.items()}, {"unknown": 10, "gpt-5.3-codex": 10, "gpt-5.5": 10})

    def test_a_file_that_does_not_open_with_its_session_meta_is_malformed(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"), record("r1", "t1", usage(10, 0, 1))])
        self.write("rollout-b.jsonl", [turn("t1", "gpt-5.5"), meta("b", self.repo)])
        self.write("rollout-c.jsonl", [meta("c", self.repo), '{"type": "token_usage_record", BROKEN'])
        result = self.scan()
        self.assertEqual((result.malformed, result.days["2026-09-01"]["turns"]), (2, 1))

    def test_an_empty_rollout_is_not_malformed(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"), record("r1", "t1", usage(10, 0, 1))])
        path = os.path.join(self.home, "sessions", "2026", "09", "01", "rollout-b.jsonl")
        open(path, "w").close()
        self.assertEqual(self.scan().malformed, 0)

    def test_a_file_with_unexpected_shapes_is_unreadable_not_fatal(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"), record("r1", "t1", usage(10, 0, 1))])
        self.write("rollout-b.jsonl", [{"timestamp": TS, "type": "session_meta", "payload": ["not", "a", "dict"]}])
        self.write("rollout-c.jsonl", [meta("c", self.repo), turn("t1", "gpt-5.5"), record("r2", "t1", ["not", "usage"])])
        result = self.scan()
        self.assertEqual((result.days["2026-09-01"]["turns"], result.skipped), (1, 2))

    def test_an_id_model_or_timestamp_of_the_wrong_type_is_read_as_missing(self):
        def at(line, stamp):
            return dict(line, timestamp=stamp)
        odd = (["x"], {"x": 1})
        for n, value in enumerate(odd):
            # An id that is not a string is no id: the file stands for itself.
            self.write(f"rollout-{n}a.jsonl", [meta(value, self.repo), turn("t1", "gpt-5.5"), record(f"a{n}", "t1", usage(10, 0, 1))])
            # A fork parent that is not a string names no parent.
            self.write(f"rollout-{n}b.jsonl", [meta(f"b{n}", self.repo, forked_from=value),
                                               turn("t1", "gpt-5.5"), record(f"b{n}", "t1", usage(10, 0, 1))])
            # A model that is not a string is unknown.
            self.write(f"rollout-{n}c.jsonl", [meta(f"c{n}", self.repo), turn("t1", value), record(f"c{n}", "t1", usage(10, 0, 1))])
            # A response id that is not a string deduplicates nothing.
            self.write(f"rollout-{n}d.jsonl", [meta(f"d{n}", self.repo), turn("t1", "gpt-5.5"), record(value, "t1", usage(10, 0, 1))])
            # A turn id that is not a string names no turn; the latest model still applies.
            self.write(f"rollout-{n}e.jsonl", [meta(f"e{n}", self.repo), dict(turn(value, "gpt-5.5")),
                                               record(f"e{n}", "t1", usage(10, 0, 1))])
            # A timestamp that is not an ISO date string puts the usage on no
            # day: the event before the record, which would count, and the record.
            self.write(f"rollout-{n}f.jsonl", [meta(f"f{n}", self.repo), turn("t1", "gpt-5.5"),
                                               at(count(usage(10, 0, 1), usage(10, 0, 1)), value),
                                               at(record(f"f{n}", "t1", usage(10, 0, 1)), value)])
        result = self.scan()
        self.assertEqual((result.skipped, result.malformed), (0, 0))
        self.assertEqual(result.days, {"2026-09-01": {"turns": 10, "models": {
            "gpt-5.5": {"input": 80, "output": 8, "cache_read": 0, "cache_write": 0},
            "unknown": {"input": 20, "output": 2, "cache_read": 0, "cache_write": 0}}}})

    def test_a_count_that_is_not_an_integer_reads_as_zero(self):
        self.write("rollout-a.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"),
                                       record("r1", "t1", dict(usage(10, 0, 1), input_tokens="ten")),
                                       record("r2", "t1", dict(usage(10, 0, 1), output_tokens=1.5))])
        result = self.scan()
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.days["2026-09-01"]["models"]["gpt-5.5"],
                         {"input": 10, "output": 1, "cache_read": 0, "cache_write": 0})

    def test_other_files_in_the_homes_are_ignored(self):
        self.write("notes.jsonl", [meta("a", self.repo), turn("t1", "gpt-5.5"), record("r1", "t1", usage(10, 0, 1))])
        self.assertIsNone(self.scan())

    @unittest.skipUnless(codex.zstd, "compression.zstd arrived in Python 3.14")
    def test_a_compressed_rollout_is_read(self):
        self.write("rollout-a.jsonl.zst", [meta("a", self.repo), turn("t1", "gpt-5.5"),
                                           record("r1", "t1", usage(10, 0, 1))], opener=codex.zstd.open)
        self.assertEqual(self.day()["turns"], 1)

    @unittest.skipUnless(codex.zstd, "compression.zstd arrived in Python 3.14")
    def test_a_corrupt_compressed_rollout_is_counted_as_unreadable(self):
        self.write("rollout-a.jsonl.zst", ["not zstd data"])
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_without_zstd_a_compressed_rollout_is_counted_as_unreadable(self):
        self.write("rollout-a.jsonl.zst", ["never opened"])
        with mock.patch.object(codex, "zstd", None):
            result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))
        self.assertIn("3.14", codex.SKIPPED)


if __name__ == "__main__":
    unittest.main()
