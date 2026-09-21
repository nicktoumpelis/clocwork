"""Qwen Code: a fork of Gemini CLI, with two generations of session logs.

From 0.4.0 each session is a JSONL file under
<runtime>/projects/<path>/chats/<session id>.jsonl, where the runtime
directory is QWEN_RUNTIME_DIR, else QWEN_HOME, else ~/.qwen. Every record
carries the working directory it was written in, and every API call -- the
main one and the side calls, such as the memory extractor's -- writes a
`ui_telemetry` system record whose uiEvent is a `qwen-code.api_response` with
the call's own timestamp, model, auth type and token counts. Those records are
what is read here: the assistant message's usageMetadata repeats the main
call's counts and misses the side calls, and the per-call ledger 0.19.0 added
under usage/ names no working directory.

Before 0.4.0 the sessions are Gemini CLI's own format under
<runtime>/tmp/<sha256 of the project path>/chats/, with a model's messages
typed "qwen", and gemini.scan reads them.

Qwen normalises every provider's counts before it logs them: input includes
the cache read, and for Anthropic the cache write as well, which is then
reported nowhere apart from it and is counted here as input. Whether a
record's reasoning already sits inside its output is decided by the record's
own total, as gemini.counters does: OpenAI's and Anthropic's totals are input
+ output, Gemini's add the thoughts beside the output. Where a record has no
total, its auth type decides. The OpenAI and Anthropic conventions were
checked by pointing Qwen Code 0.24.2 at a local mock of each API that
returned distinctive counts; the Gemini one was not, because the SDK would
not accept the mock's stream, and is Gemini CLI's convention taken on trust.
"""

import json
import os
import re

from clocwork import tokens
from clocwork.sources import gemini

KEY = "qwen"
LABEL = "Qwen Code"
# agents.VENDORS reports Qwen Code's own trailer, `Co-authored-by: Qwen-Coder
# <qwen-coder@alibabacloud.com>`, which it appends to the commits it makes, as
# "Qwen Code".
AGENT = re.compile(r"^Qwen Code$")
SKIPPED = "damaged, or not readable as text"
READ_ERRORS = (OSError, UnicodeError)
# Only these lines are parsed; the rest of a session is prompts and replies.
EVENT = '"qwen-code.api_response"'
# The auth types whose output already holds the reasoning, as their totals
# show when they have one: OpenAI's convention, which Qwen's own OAuth
# endpoint and its Responses client follow, and Anthropic's as Qwen logs it.
REASONING_INSIDE = ("openai", "openai-responses", "qwen-oauth", "anthropic")


def default_homes(env):
    """The runtime directory, and the global one when the runtime directory
    has been moved away from it: sessions written before QWEN_RUNTIME_DIR was
    set stay where they were."""
    global_dir = os.path.expanduser(env.get("QWEN_HOME") or os.path.join("~", ".qwen"))
    runtime = env.get("QWEN_RUNTIME_DIR")
    runtime = os.path.expanduser(runtime) if runtime else None
    return [runtime, global_dir] if runtime and runtime != global_dir else [global_dir]


def chat_logs(homes):
    """Every 0.4.0-and-later session file under the homes, each once, and how
    many directories could not be listed."""
    found, unreadable = set(), 0
    for home in homes:
        projects = os.path.join(home, "projects")
        if not os.path.isdir(projects):
            continue
        try:
            names = sorted(os.listdir(projects))
        except OSError:
            unreadable += 1
            continue
        for project in names:
            chats = os.path.join(projects, project, "chats")
            if not os.path.isdir(chats):
                continue
            try:
                found |= {os.path.join(chats, name) for name in os.listdir(chats) if name.endswith(".jsonl")}
            except OSError:
                unreadable += 1
    return sorted(found), unreadable


def inside(path, repo_real):
    """Whether a working directory is the repository or a directory in it:
    any directory, tracked or not, as the other readers that record one
    judge it."""
    real = os.path.realpath(path)
    return real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep)


def usage_of(event):
    """An event's counts in the shape gemini.counters reads. A record with no
    total has its auth type stand in for the evidence a total would give."""
    usage = {"input": event.get("input_token_count"), "output": event.get("output_token_count"),
             "cached": event.get("cached_content_token_count"),
             "thoughts": event.get("thoughts_token_count"), "tool": event.get("tool_token_count"),
             "total": event.get("total_token_count")}
    if not tokens.count(usage["total"]) and event.get("auth_type") in REASONING_INSIDE:
        usage["total"] = tokens.count(usage["input"]) + tokens.count(usage["output"])
    return usage


def read_chat(lines, path, calls):
    """Add one session file's API calls to `calls`, keyed by record id; the
    lines that would not parse. A call is (working directory, date, model,
    tokens in the shape gemini.counters reads)."""
    malformed = 0
    for n, line in enumerate(lines):
        if EVENT not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        payload = rec.get("systemPayload") if isinstance(rec, dict) else None
        event = payload.get("uiEvent") if isinstance(payload, dict) else None
        if not isinstance(event, dict) or event.get("event.name") != "qwen-code.api_response":
            continue
        # A record copied into another file keeps its id, so it is one call.
        key = tokens.text(rec.get("uuid")) or f"{path}:{n}"
        calls[key] = (tokens.text(rec.get("cwd")),
                      tokens.day(event.get("event.timestamp")) or tokens.day(rec.get("timestamp")),
                      tokens.text(event.get("model")), usage_of(event))
    return malformed


def add_days(days, more):
    for date, day in more.items():
        for model, counts in day["models"].items():
            tokens.record(days, date, model, counts, turns=0)
        days.setdefault(date, {"turns": 0, "models": {}})["turns"] += day["turns"]


def scan(repo, homes):
    """The repository's Qwen Code usage, or None when no session belongs to it
    and nothing was unreadable."""
    repo_real = os.path.realpath(repo)
    calls, malformed = {}, 0
    files, skipped = chat_logs(homes)
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                malformed += read_chat(f, path, calls)
        except READ_ERRORS:
            skipped += 1
    days, belonged, placed = {}, False, {}
    for cwd, date, model, usage in calls.values():
        if cwd and cwd not in placed:
            placed[cwd] = inside(cwd, repo_real)
        if not cwd or not placed[cwd]:
            continue
        belonged = True
        if not date:
            malformed += 1
            continue
        counts = gemini.counters(usage)
        if any(counts.values()):
            tokens.record(days, date, model, counts)
    legacy = gemini.scan(repo, [os.path.join(home, "tmp") for home in homes], kind="qwen")
    if legacy is not None:
        belonged = True
        add_days(days, legacy.days)
        malformed += legacy.malformed
        skipped += legacy.skipped
    if not belonged and not skipped:
        return None
    return tokens.ScanResult(days, malformed, skipped)
