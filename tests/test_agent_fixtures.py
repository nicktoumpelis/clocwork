"""The committed agent logs carry only what the token readers need.

tests/fixtures holds real Codex CLI, Gemini CLI and OpenCode sessions from
public repositories, reduced to identity, model, usage and timestamps. These
checks fail if a later refresh lets anything else in: a prompt, a reply, a
real path.
"""

import os
import unittest

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
# A model id can hold a slash of its own, so these are not paths that
# escaped the reduction. Every one is a model the fixtures record.
MODEL_IDS = {"Qwen/Qwen3-Coder-Next", "openagents/khala", "qwen/qwen3-4b"}
AGENTS = ("codex", "gemini", "opencode")


def keys_of(value):
    if isinstance(value, dict):
        return set(value).union(*(keys_of(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_of(v) for v in value))
    return set()


def strings_of(value):
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings_of(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings_of(v)]
    return [value] if isinstance(value, str) else []


class TestFixturesAreReduced(unittest.TestCase):
    def test_every_agent_has_its_sessions(self):
        self.assertEqual(tuple(len(agent_logs.files(a)) for a in AGENTS), (13, 5, 17))

    def test_only_allow_listed_keys(self):
        for agent, allowed in (("codex", CODEX_KEYS), ("gemini", GEMINI_KEYS), ("opencode", OPENCODE_KEYS)):
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    found = set().union(*(keys_of(r) for r in agent_logs.records(agent, rel)))
                    self.assertLessEqual(found, allowed)

    def test_no_path_or_remote_but_the_placeholders(self):
        for agent in AGENTS:
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    strings = {s for r in agent_logs.records(agent, rel) for s in strings_of(r)}
                    left = {s for s in strings if "/" in s} - {agent_logs.PLACEHOLDER, agent_logs.REMOTE} - MODEL_IDS
                    self.assertEqual(left, set())

    def test_every_gemini_session_names_the_placeholder_project(self):
        want = agent_logs.project_hash(agent_logs.PLACEHOLDER)
        for rel in agent_logs.files("gemini"):
            hashes = {r["projectHash"] for r in agent_logs.records("gemini", rel) if "projectHash" in r}
            self.assertEqual(hashes, {want}, rel)

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
                       "Copyright (c) 2026 Furkan Kalaycioglu", "Copyright (c) 2025 Ingo Eichhorst",
                       "Permission is hereby granted, free of charge",
                       # OpenCode's four sources, each at the commit read.
                       "OpenAgentsInc/openagents", "8f84d05896ef14edee491621bf977ee5315cc8ed",
                       "remorses/kimaki", "4a36f47e45bf4778f682c145d98c8511adb272b1",
                       "rjx18/codor", "03481a33f87f8b16b8a35522084e37ebf7c9c168",
                       "7812f069afad9289a615cb968c375dfaed093780",
                       "Copyright (c) 2025 Kimaki", "Copyright (c) 2026 Richard Xiong",
                       "Apache License, Version 2.0"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
