"""The committed agent logs carry only what the token readers need.

tests/fixtures holds real Codex CLI, Copilot CLI, Gemini CLI, Kilo Code and
OpenCode sessions from public repositories, reduced to identity, model,
usage and timestamps. These checks fail if a later refresh lets anything else in: a
prompt, a reply, a real path.
"""

import os
import re
import unittest

from clocwork import paths
from tests import agent_logs

CODEX_KEYS = {
    "cache_write_input_tokens", "cached_input_tokens", "cli_version", "cwd", "depth", "forked_from_id",
    "git", "id", "info", "input_tokens", "last_token_usage", "model", "model_context_window",
    "model_provider", "ordinal", "originator", "output_tokens", "parent_thread_id", "payload",
    "reasoning_output_tokens", "repository_url", "response_id", "role", "root_turn_id", "session_id",
    "source", "subagent", "thread_id", "thread_spawn", "thread_token_usage", "timestamp",
    "total_token_usage", "total_tokens", "turn_id", "turn_token_usage", "type", "usage",
}
GEMINI_KEYS = {
    "$rewindTo", "$set", "cached", "id", "input", "kind", "lastUpdated", "messages", "model", "output",
    "projectHash", "sessionId", "startTime", "thoughts", "timestamp", "tokens", "tool", "total", "type",
}
# OpenCode's own column and field names, in both spellings the schema has
# used (project_id and projectID, and so on).
OPENCODE_KEYS = {
    "agent", "cache", "completed", "cost", "created", "cwd", "data", "directory", "finish", "id",
    "input", "messageID", "message_id", "mode", "model", "modelID", "output", "parentID", "parent_id",
    "path", "projectID", "project_id", "providerID", "read", "reason", "reasoning", "role", "root",
    "seq", "sessionID", "session_id", "time", "time_created", "time_updated", "tokens", "total",
    "type", "updated", "variant", "version", "write",
}
# The fields that name a model. A model id can hold a slash of its own
# (`qwen/qwen3-4b`), so a slash under one of these is not a path that escaped
# the reduction - but a slash anywhere else is, whatever it happens to spell.
# A recorded `model-switched` row nests the id as `model: {id: ...}`, so it is
# the whole field path that decides, not the name the value sits directly
# under.
MODEL_KEYS = {"model", "modelID"}
# Copilot records its usage in a table keyed by model id, so the names under
# these fields are data rather than field names: they are checked for the
# shape of a model id instead of being named in an allow-list, which a
# refresh recording another model would otherwise have to grow.
MODEL_KEYED = {"modelMetrics"}
# No slash: every model id these recordings hold is a bare name, and a
# slash is what an owner/name or a path that escaped the reduction would
# bring. A refresh that records a provider-qualified id fails here, which is
# the point at which someone should look at it rather than widen this by
# reflex.
MODEL_ID = re.compile(r"^[0-9a-z][0-9a-z.-]*$")
# The remote's owner/name. Copilot records the two halves of a remote apart,
# as repositoryHost and repository, so the path half stands alone in a
# reduced record and is a placeholder like the remote it comes from.
REMOTE_PATH = paths.parse_remote(agent_logs.REMOTE)[1]
AGENTS = ("codex", "copilot", "copilot-store", "gemini", "kilo", "opencode")
COPILOT_KEYS = {
    "baseCommit", "branch", "cacheReadTokens", "cacheWriteTokens", "cache_read", "cache_write",
    "context", "copilotVersion", "cost", "count", "cwd", "data", "gitRoot", "headCommit", "hostType",
    "input", "inputTokens", "model", "modelMetrics", "output", "outputTokens", "reasoningTokens",
    "repository", "repositoryHost", "requests", "resumeTime", "sessionId", "shutdownType",
    "startTime", "timestamp", "tokenCount", "tokenDetails", "totalNanoAiu", "totalPremiumRequests",
    "type", "usage",
}
# The columns each table of the OpenCode fixtures uses. These are the
# spellings the recordings hold, not every one the reader accepts: `pick()`
# takes `sessionID` for `session_id` too, because the schema has used both.
# Pinning the set means a key nobody meant - one valid for another table, or
# a spelling these fixtures do not use - fails here instead of quietly
# becoming a column of its own and leaving the real one empty.
# Kilo Code's rows are OpenCode's, plus the session roll-up its
# session_usage migration added - which the reader must not count, and which
# is pinned here so a fixture refresh cannot quietly drop the columns that
# prove it does not.
# The 1.0.87 store fixture: the same log records, plus the columns its two
# tables keep and the two keys of each token_details_json bucket.
COPILOT_STORE_COLUMNS = {
    "sessions": {"id", "cwd", "repository", "branch", "created_at"},
    "assistant_usage_events": {"id", "session_id", "turn_index", "model", "input_tokens",
                               "output_tokens", "cache_read_tokens", "cache_write_tokens",
                               "reasoning_tokens", "initiator", "finish_reason",
                               "token_details_json", "created_at"},
}
COPILOT_STORE_KEYS = (COPILOT_KEYS | {"tokenType"}
                      | set().union(*COPILOT_STORE_COLUMNS.values()))
KILO_KEYS = {
    "cache", "cost", "created", "data", "directory", "id", "input", "message_id", "model",
    "modelID", "output", "parent_id", "path", "project_id", "providerID", "read", "reasoning",
    "role", "session_id", "time", "time_created", "time_updated", "tokens", "tokens_cache_read",
    "tokens_cache_write", "tokens_input", "tokens_output", "tokens_reasoning", "total", "type",
    "version", "write",
}
KILO_COLUMNS = {
    "session": {"id", "project_id", "parent_id", "directory", "version", "path",
                "time_created", "time_updated", "cost", "tokens_input", "tokens_output",
                "tokens_reasoning", "tokens_cache_read", "tokens_cache_write"},
    "message": {"id", "session_id", "time_created", "data"},
    "part": {"id", "message_id", "session_id", "time_created", "data"},
}
OPENCODE_COLUMNS = {
    "session": {"id", "project_id", "parent_id", "directory", "version", "path",
                "time_created", "time_updated"},
    "message": {"id", "session_id", "time_created", "time_updated", "data"},
    "part": {"id", "message_id", "session_id", "time_created", "time_updated", "data"},
    "session_message": {"id", "session_id", "type", "seq", "time_created", "time_updated", "data"},
}


def keys_of(value, under=None):
    """Every field name in a record. The keys of a dict under a model-keyed
    field are model ids, not field names, so they are left out and checked
    by model_ids() instead."""
    if isinstance(value, dict):
        names = set() if under in MODEL_KEYED else set(value)
        return names.union(*(keys_of(v, k) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(*(keys_of(v, under) for v in value))
    return set()


def model_ids(value, under=None):
    """Every name a record uses as a model id: the keys of a dict under a
    model-keyed field."""
    if isinstance(value, dict):
        found = set(value) if under in MODEL_KEYED else set()
        return found.union(*(model_ids(v, k) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(*(model_ids(v, under) for v in value))
    return set()


def placeholder(s):
    """Whether a string that holds a slash is one of the placeholders a
    reduced record may name: the repository's path, a directory below it,
    the remote, or the owner/name that remote spells."""
    return (s in (agent_logs.PLACEHOLDER, agent_logs.REMOTE, REMOTE_PATH)
            or s.startswith(agent_logs.PLACEHOLDER + "/"))


def named_strings(value, path=()):
    """Every string in a record, with the field path it sits under. A value
    has to be judged by where it is, not by what it spells: a leaked path
    that happened to read like a model id would pass a check that only
    looked at the text."""
    if isinstance(value, dict):
        return [pair for k, v in value.items() for pair in named_strings(v, path + (k,))]
    if isinstance(value, list):
        return [pair for v in value for pair in named_strings(v, path)]
    return [(path, value)] if isinstance(value, str) else []


def names_a_model(path):
    """Whether a field path is one a model id is recorded under."""
    return bool(set(path) & MODEL_KEYS)


class TestFixturesAreReduced(unittest.TestCase):
    def test_every_agent_has_its_sessions(self):
        self.assertEqual(tuple(len(agent_logs.files(a)) for a in AGENTS), (13, 4, 3, 5, 3, 17))

    def test_only_allow_listed_keys(self):
        for agent, allowed in (("codex", CODEX_KEYS), ("copilot", COPILOT_KEYS),
                               ("copilot-store", COPILOT_STORE_KEYS),
                               ("gemini", GEMINI_KEYS), ("kilo", KILO_KEYS),
                               ("opencode", OPENCODE_KEYS)):
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    records = agent_logs.records(agent, rel)
                    self.assertTrue(records, "a fixture file with no records is checked against nothing")
                    found = set().union(*(keys_of(r) for r in records))
                    self.assertLessEqual(found, allowed)

    def test_no_path_or_remote_but_the_placeholders(self):
        for agent in AGENTS:
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    records = agent_logs.records(agent, rel)
                    self.assertTrue(records, "a fixture file with no records is checked against nothing")
                    pairs = {p for r in records for p in named_strings(r)}
                    left = {(".".join(path), s) for path, s in pairs
                            if "/" in s and not names_a_model(path) and not placeholder(s)}
                    self.assertEqual(left, set())

    def test_the_placeholder_check_reads_the_field_not_the_text(self):
        # The guard above must not be satisfiable by naming a leaked path
        # after a model. A slash under a model field is allowed, nested or
        # not, because that is where a model id lives; under any other field
        # it is a path, whatever it spells.
        leak = {"data": {"modelID": "qwen/qwen3-4b",
                         "model": {"id": "openagents/khala"},
                         "path": {"cwd": "/Users/someone/code/thing"},
                         "note": "qwen/qwen3-4b",
                         # Most fields here are named *ID, so a rule that
                         # allowed any field whose name holds "id" would let
                         # this one by.
                         "sessionID": "a/b"}}
        found = {(".".join(path), s) for path, s in named_strings(leak)
                 if "/" in s and not names_a_model(path)}
        self.assertEqual(found, {("data.path.cwd", "/Users/someone/code/thing"),
                                 ("data.note", "qwen/qwen3-4b"),
                                 ("data.sessionID", "a/b")})

    def test_a_model_keyed_field_holds_model_ids_and_nothing_else(self):
        found = set().union(*(model_ids(r) for rel in agent_logs.files("copilot")
                              for r in agent_logs.records("copilot", rel)))
        self.assertTrue(found, "no model-keyed field found, so this guard read nothing")
        for name in sorted(found):
            with self.subTest(model=name):
                self.assertRegex(name, MODEL_ID)

    def test_the_model_id_shape_rejects_a_path(self):
        # The guard above stands in for an allow-list, so it has to reject
        # what an allow-list would have caught -- including the shapes that
        # hold exactly one slash, which is what an owner/name leak looks
        # like and which an earlier version of this pattern allowed.
        for leak in ("/Users/someone/code/thing", "Users/someone/code", "../elsewhere",
                     "someone/private", "example/agent-sample", "openai/gpt-5",
                     "C:\\Users\\someone", "a prompt about gpt-5-mini", ""):
            with self.subTest(leak=leak):
                self.assertNotRegex(leak, MODEL_ID)

    def test_the_placeholder_rule_allows_no_other_path(self):
        for leak in ("/Users/someone/code/thing", "/work/agent-sample-other/x",
                     "https://github.com/someone/private.git", "someone/private"):
            with self.subTest(leak=leak):
                self.assertFalse(placeholder(leak))
        for allowed in (agent_logs.PLACEHOLDER, agent_logs.PLACEHOLDER + "/src/app",
                        agent_logs.REMOTE, REMOTE_PATH):
            with self.subTest(allowed=allowed):
                self.assertTrue(placeholder(allowed))

    def test_every_gemini_session_names_the_placeholder_project(self):
        want = agent_logs.project_hash(agent_logs.PLACEHOLDER)
        for rel in agent_logs.files("gemini"):
            hashes = {r["projectHash"] for r in agent_logs.records("gemini", rel) if "projectHash" in r}
            self.assertEqual(hashes, {want}, rel)

    def test_the_opencode_rows_name_only_their_tables_columns(self):
        # install() infers each table's columns from the rows, so a key
        # nobody meant would become a column of its own and leave the one the
        # reader looks for empty. Each file's keys must be columns of its
        # table, and the table's rows together must use every column named -
        # an unused name would make this guard laxer than it reads.
        seen = {}
        for rel in agent_logs.files("opencode"):
            if not rel.split(os.sep)[0].startswith("s1"):
                continue
            table = os.path.splitext(os.path.basename(rel))[0]
            rows = agent_logs.records("opencode", rel)
            keys = set().union(*(set(r) for r in rows)) if rows else set()
            with self.subTest(file=rel):
                self.assertIn(table, OPENCODE_COLUMNS)
                self.assertTrue(rows, "a fixture table with no rows tests nothing")
                self.assertLessEqual(keys, OPENCODE_COLUMNS[table])
            seen.setdefault(table, set()).update(keys)
        self.assertEqual(seen, OPENCODE_COLUMNS)

    def test_the_kilo_rows_name_only_their_tables_columns(self):
        # Same reason as OpenCode's: install() infers each table's columns
        # from the rows, so a key nobody meant becomes a column of its own
        # and leaves the one the reader looks for empty.
        seen = {}
        for rel in agent_logs.files("kilo"):
            table = os.path.splitext(os.path.basename(rel))[0]
            rows = agent_logs.records("kilo", rel)
            with self.subTest(file=rel):
                self.assertIn(table, KILO_COLUMNS)
                self.assertTrue(rows, "a fixture table with no rows tests nothing")
                self.assertLessEqual(set().union(*(set(r) for r in rows)), KILO_COLUMNS[table])
            seen.setdefault(table, set()).update(*(set(r) for r in rows))
        # Every column named must be used by some row, or the guard above is
        # laxer than it reads -- the same property OpenCode's pins.
        self.assertEqual(seen, KILO_COLUMNS)

    def test_the_copilot_store_rows_name_only_their_tables_columns(self):
        # The same guard, for the tables install() builds session-store.db
        # from: the reader selects these columns by name.
        seen = {}
        for rel in agent_logs.files("copilot-store"):
            if not rel.startswith("s1" + os.sep):
                continue
            table = os.path.splitext(os.path.basename(rel))[0]
            rows = agent_logs.records("copilot-store", rel)
            with self.subTest(file=rel):
                self.assertIn(table, COPILOT_STORE_COLUMNS)
                self.assertTrue(rows, "a fixture table with no rows tests nothing")
                self.assertLessEqual(set().union(*(set(r) for r in rows)),
                                     COPILOT_STORE_COLUMNS[table])
            seen.setdefault(table, set()).update(*(set(r) for r in rows))
        self.assertEqual(seen, COPILOT_STORE_COLUMNS)

    def test_the_kilo_session_row_carries_the_roll_up_it_must_ignore(self):
        # The reader is only shown ignoring these columns if they are here.
        rows = agent_logs.records("kilo", os.path.join("s1-derived", "session.jsonl"))
        self.assertEqual(len(rows), 1)
        for column in ("cost", "tokens_input", "tokens_output", "tokens_reasoning",
                       "tokens_cache_read", "tokens_cache_write"):
            with self.subTest(column=column):
                self.assertIn(column, rows[0])
        self.assertEqual(rows[0]["tokens_input"], 20_158)

    def test_the_kilo_buckets_say_which_rows_were_recorded(self):
        # The export holds no session row, so that one is derived; the
        # message and part rows are as recorded.
        self.assertEqual({rel.split(os.sep)[0] for rel in agent_logs.files("kilo")},
                         {"s1", "s1-derived"})

    def test_the_opencode_buckets_are_what_the_readme_describes(self):
        # Provenance is the point of the three buckets: a test that claims a
        # recorded count must be able to say which recording it came from.
        buckets = {rel.split(os.sep)[0] for rel in agent_logs.files("opencode")}
        self.assertEqual(buckets, {"s1", "s1-derived", "s1-synthetic", "storage", "project"})
        # Every database bucket names its table in the file name, and the
        # reader needs a session and a message from somewhere.
        tables = {os.path.splitext(os.path.basename(rel))[0]
                  for rel in agent_logs.files("opencode") if rel.split(os.sep)[0].startswith("s1")}
        self.assertEqual(tables, {"session", "message", "part", "session_message"})

    def test_the_readme_credits_every_source_and_its_licence(self):
        with open(os.path.join(agent_logs.FIXTURES, "README.md"), encoding="utf-8") as f:
            text = f.read()
        for needle in ("furkankly/zoetrope", "b1f31dd26bd4e9e513885e39edb78d0850a5d1fe",
                       "ingo-eichhorst/Irrlicht", "a3f1f8d4683e1194049a92b6b40e44d0aa11aef0",
                       # The Copilot CLI recordings, from a later commit.
                       "bf9c07a50c715afde1b8f674061ef49fff9d9b27",
                       "Copyright (c) 2026 Furkan Kalaycioglu", "Copyright (c) 2025 Ingo Eichhorst",
                       "Permission is hereby granted, free of charge",
                       # OpenCode's six sources, each at the commit read.
                       "OpenAgentsInc/openagents", "8f84d05896ef14edee491621bf977ee5315cc8ed",
                       "remorses/kimaki", "4a36f47e45bf4778f682c145d98c8511adb272b1",
                       "rjx18/codor", "03481a33f87f8b16b8a35522084e37ebf7c9c168",
                       "7812f069afad9289a615cb968c375dfaed093780",
                       "xiopt/tmux-pane-dash", "1b358b9608e29fe550052ac5c9c13417cf2c9c95",
                       "karta0807913/opencode.el", "31fccf10566c2e84e11d60f7f5fddb4fdc1c9689",
                       "Copyright (c) 2025 Kimaki", "Copyright (c) 2026 Richard Xiong",
                       "Copyright (c) 2026 xiopt",
                       # The Copilot CLI store, recorded for this repository.
                       "copilot-store/", "Copilot CLI 1.0.87",
                       # Kilo Code's recorded session.
                       "autonomous-ai/openharness", "a67e082b6e2985e7f226bf5737ebd3b39ce1d60b",
                       # openharness was Apache-2.0 at the commit its rows
                       # come from, so its NOTICE attribution is carried,
                       # not an MIT copyright line.
                       "Copyright 2026 Autonomous, Inc.",
                       "This product includes software developed at Autonomous, Inc.",
                       "Apache License, Version 2.0"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
