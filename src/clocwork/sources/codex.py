"""Codex CLI: one JSONL rollout per session under $CODEX_HOME/sessions/YYYY/MM/DD/,
moved flat into archived_sessions/ when archived, and compressed to
.jsonl.zst once cold.

Two usage formats exist. From CLI 0.153.4 every model response writes a
token_usage_record with that response's usage and id; earlier versions write
only token_count events, each carrying the session's running total and the
increment just added to it. A forked session starts with a copy of its
parent's token_count events, re-timestamped. Those copies are recognised by
their (total, increment) pair and dropped, but only when the fork's parent
holds the pair: unrelated sessions that open with the same prompt report
identical first pairs, and those are real usage. The public
recordings in tests/fixtures/codex hold both formats, sub-agents and a fork.
"""

import json
import os
import re

from clocwork import paths, tokens

try:
    from compression import zstd
except ImportError:             # before Python 3.14
    zstd = None

KEY = "codex"
LABEL = "Codex CLI"
# Codex asks for "Co-authored-by: Codex <noreply@openai.com>" on its commits.
AGENT = re.compile(r"^Codex\b")
SKIPPED = "compressed rollouts need Python 3.14 or later"

READ_ERRORS = (OSError, EOFError, UnicodeError) + ((zstd.ZstdError,) if zstd else ())
# Only these lines matter; messages, tool calls and other events are skipped
# before they are parsed.
WANTED = ('"turn_context"', '"token_usage_record"', '"token_count"')


def default_homes(env):
    home = env.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return [os.path.join(home, "sessions"), os.path.join(home, "archived_sessions")]


def rollouts(homes):
    """Every rollout under the homes, plain or compressed, in path order."""
    found = []
    for home in homes:
        for directory, _dirs, files in os.walk(home):
            found += [os.path.join(directory, name) for name in files
                      if name.startswith("rollout-") and name.endswith((".jsonl", ".jsonl.zst"))]
    return sorted(found)


def belongs(meta, repo_real, remote):
    """Whether a session ran in the repository: the same remote when both
    name one, as paths.check_identity decides, else a working directory at
    or below the repository's."""
    url = (meta.get("git") or {}).get("repository_url")
    if remote and isinstance(url, str) and url:
        parsed = paths.parse_remote(url)
        return parsed is not None and f"{parsed[0]}/{parsed[1]}".lower() == remote.lower()
    cwd = meta.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False
    real = os.path.realpath(cwd)
    return real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep)


def counts(usage):
    return tokens.inclusive(usage.get("input_tokens"), usage.get("output_tokens"),
                            usage.get("cached_input_tokens"), usage.get("cache_write_input_tokens"))


def read_session(lines, repo_real, remote):
    """(session, malformed lines) for one rollout, or (None, n) when it is
    not the repository's or does not open with its session_meta.

    A session is {"id", "forked_from", "records", "events"}: records are
    (response_id, date, model, counts) from token_usage_record lines, events
    are (pair, date, model, counts) from token_count lines whose running
    total moved.
    """
    try:
        head = json.loads(next(lines, ""))
    except ValueError:
        return None, 1
    if not isinstance(head, dict) or head.get("type") != "session_meta":
        return None, 1
    meta = head.get("payload") or {}
    if not belongs(meta, repo_real, remote):
        return None, 0
    session = {"id": meta.get("id"), "forked_from": meta.get("forked_from_id"), "records": [], "events": []}
    turn_models, model, previous, malformed = {}, None, None, 0
    for line in lines:
        if not any(marker in line for marker in WANTED):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if not isinstance(rec, dict):
            continue
        kind, payload = rec.get("type"), rec.get("payload") or {}
        date = (rec.get("timestamp") or "")[:10]
        if kind == "turn_context":
            model = payload.get("model") or model
            if payload.get("turn_id"):
                turn_models[payload["turn_id"]] = payload.get("model")
        elif kind == "token_usage_record":
            session["records"].append((payload.get("response_id"), date,
                                       turn_models.get(payload.get("turn_id")) or model,
                                       counts(payload.get("usage") or {})))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total, last = info.get("total_token_usage"), info.get("last_token_usage")
            if not total or not last or total == previous:
                continue            # no usage yet, or the running total repeated
            previous = total
            session["events"].append((json.dumps([total, last], sort_keys=True), date, model, counts(last)))
    return session, malformed


def replayed(session, by_id):
    """How many of a session's leading token_count events were copied from
    its parent when it was forked. A fork's file holds its whole inherited
    history, so the parent's events already include every earlier
    generation's."""
    parent = by_id.get(session["forked_from"])
    inherited = {pair for pair, *_rest in parent["events"]} if parent else set()
    n = 0
    while n < len(session["events"]) and session["events"][n][0] in inherited:
        n += 1
    return n


def scan(repo, homes):
    """The repository's Codex usage, or None when no rollout in the homes
    belongs to it and none was unreadable."""
    repo_real = os.path.realpath(repo)
    remote = paths.remote_key(repo) if os.path.isdir(repo) else None
    sessions, malformed, skipped = [], 0, 0
    for path in rollouts(homes):
        compressed = path.endswith(".zst")
        if compressed and zstd is None:
            skipped += 1
            continue
        try:
            with (zstd.open if compressed else open)(path, "rt", encoding="utf-8", errors="replace") as f:
                session, bad = read_session(iter(f), repo_real, remote)
        except READ_ERRORS:
            skipped += 1
            continue
        malformed += bad
        if session is not None:
            sessions.append(session)
    if not sessions and not skipped:
        return None

    days, responses = {}, set()
    by_id = {s["id"]: s for s in sessions if s["id"]}

    def add(date, model, c):
        # An all-zero record is a context-window fill, not a response.
        if date and any(c.values()):
            tokens.record(days, date, model, c)

    for s in sessions:
        if s["records"]:
            for response_id, date, model, c in s["records"]:
                if response_id is not None:
                    if response_id in responses:
                        continue
                    responses.add(response_id)
                add(date, model, c)
        else:
            for _pair, date, model, c in s["events"][replayed(s, by_id):]:
                add(date, model, c)
    return tokens.ScanResult(days, malformed, skipped)
