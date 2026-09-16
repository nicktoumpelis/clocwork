"""The committed agent logs carry only what the token readers need.

tests/fixtures holds real Codex CLI and Gemini CLI sessions from two public
repositories, reduced to identity, model, usage and timestamps. These checks
fail if a later refresh lets anything else in: a prompt, a reply, a real path.
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
    def test_both_agents_have_their_sessions(self):
        self.assertEqual((len(agent_logs.files("codex")), len(agent_logs.files("gemini"))), (13, 5))

    def test_only_allow_listed_keys(self):
        for agent, allowed in (("codex", CODEX_KEYS), ("gemini", GEMINI_KEYS)):
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    found = set().union(*(keys_of(r) for r in agent_logs.records(agent, rel)))
                    self.assertLessEqual(found, allowed)

    def test_no_path_or_remote_but_the_placeholders(self):
        for agent in ("codex", "gemini"):
            for rel in agent_logs.files(agent):
                with self.subTest(file=rel):
                    strings = {s for r in agent_logs.records(agent, rel) for s in strings_of(r)}
                    self.assertEqual({s for s in strings if "/" in s} - {agent_logs.PLACEHOLDER, agent_logs.REMOTE}, set())

    def test_every_gemini_session_names_the_placeholder_project(self):
        want = agent_logs.project_hash(agent_logs.PLACEHOLDER)
        for rel in agent_logs.files("gemini"):
            hashes = {r["projectHash"] for r in agent_logs.records("gemini", rel) if "projectHash" in r}
            self.assertEqual(hashes, {want}, rel)

    def test_the_readme_credits_both_sources_and_their_licence(self):
        with open(os.path.join(agent_logs.FIXTURES, "README.md"), encoding="utf-8") as f:
            text = f.read()
        for needle in ("furkankly/zoetrope", "b1f31dd26bd4e9e513885e39edb78d0850a5d1fe",
                       "ingo-eichhorst/Irrlicht", "a3f1f8d4683e1194049a92b6b40e44d0aa11aef0",
                       "Copyright (c) 2026 Furkan Kalaycioglu", "Copyright (c) 2025 Ingo Eichhorst",
                       "Permission is hereby granted, free of charge"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
