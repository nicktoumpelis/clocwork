"""The committed agent logs carry only what the token readers need.

tests/fixtures holds real Codex CLI, Copilot CLI, Gemini CLI and OpenCode
sessions from public repositories, reduced to identity, model, usage and
timestamps. These checks fail if a later refresh lets anything else in: a
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
MODEL_ID = re.compile(r"^[0-9a-z][0-9a-z.-]*(?:/[0-9a-z][0-9a-z.-]*)?$")
# The remote's owner/name. Copilot records the two halves of a remote apart,
# as repositoryHost and repository, so the path half stands alone in a
# reduced record and is a placeholder like the remote it comes from.
REMOTE_PATH = paths.parse_remote(agent_logs.REMOTE)[1]
AGENTS = ("codex", "copilot", "gemini", "opencode")
# The columns each table of the OpenCode fixtures uses. These are the
# spellings the recordings hold, not every one the reader accepts: `pick()`
# takes `sessionID` for `session_id` too, because the schema has used both.
# Pinning the set means a key nobody meant - one valid for another table, or
# a spelling these fixtures do not use - fails here instead of quietly
# becoming a column of its own and leaving the real one empty.
COPILOT_KEYS = {
    "baseCommit", "branch", "cacheReadTokens", "cacheWriteTokens", "cache_read", "cache_write",
    "context", "copilotVersion", "cost", "count", "cwd", "data", "gitRoot", "headCommit", "hostType",
    "input", "inputTokens", "model", "modelMetrics", "output", "outputTokens", "reasoningTokens",
    "repository", "repositoryHost", "requests", "resumeTime", "sessionId", "shutdownType",
    "startTime", "timestamp", "tokenCount", "tokenDetails", "totalNanoAiu", "totalPremiumRequests",
    "type", "usage",
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
        self.assertEqual(tuple(len(agent_logs.files(a)) for a in AGENTS), (13, 4, 5, 17))

    def test_only_allow_listed_keys(self):
        for agent, allowed in (("codex", CODEX_KEYS), ("copilot", COPILOT_KEYS),
                               ("gemini", GEMINI_KEYS), ("opencode", OPENCODE_KEYS)):
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    found = set().union(*(keys_of(r) for r in agent_logs.records(agent, rel)))
                    self.assertLessEqual(found, allowed)

    def test_no_path_or_remote_but_the_placeholders(self):
        for agent in AGENTS:
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    pairs = {p for r in agent_logs.records(agent, rel) for p in named_strings(r)}
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
        # what an allow-list would have caught.
        for leak in ("/Users/someone/code/thing", "Users/someone/code", "../elsewhere",
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
                       "Apache License, Version 2.0"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
