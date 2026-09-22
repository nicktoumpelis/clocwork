"""Qwen Code: a fork of Gemini CLI, with two generations of session logs.

From 0.4.0 each session is a JSONL file under
<runtime>/projects/<path>/chats/<session id>.jsonl, moved to chats/archive/
when it is archived, where the runtime directory is QWEN_RUNTIME_DIR, else
the advanced.runtimeOutputDir setting, else QWEN_HOME, else ~/.qwen. Every record
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
import sys

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
    moved = runtime and os.path.realpath(runtime) != os.path.realpath(global_dir)
    return [runtime, global_dir] if moved else [global_dir]


# The settings files Qwen Code merges, lowest first: the system defaults, the
# user's, the workspace's, then the system's. The system files are fixed per
# platform unless these name them.
SYSTEM_SETTINGS = {"darwin": "/Library/Application Support/QwenCode/settings.json",
                   "win32": "C:\\ProgramData\\qwen-code\\settings.json"}
LINUX_SETTINGS = "/etc/qwen-code/settings.json"
# $NAME or ${NAME}, as Qwen expands them in every settings value; a name the
# environment does not hold is left as written, and so are the session ids
# Qwen keeps for itself. (It also keeps its own internal secrets, which no
# shell running clocwork holds.)
VARIABLE = re.compile(r"\$(?:(\w+)|\{([^}]+)\})")
UNEXPANDED = {"SESSION_ID", "QWEN_CODE_SESSION_ID"}
# The comments strip-json-comments removes before Qwen parses a settings file:
# a string is matched first, so a // inside one is left alone, and a string or
# a block comment left open runs to the end of the file. An open string that
# had to close would be tried again at every later quote.
JSONC = re.compile(r'("(?:[^"\\]|\\.)*"?)|//[^\n]*|/\*.*?(?:\*/|\Z)', re.DOTALL)


def settings_files(repo, homes, env):
    """Every settings file that can name a runtime directory for a session in
    the repository. The user's is looked for in each home, and the
    workspace's at the repository's root."""
    system = env.get("QWEN_CODE_SYSTEM_SETTINGS_PATH") or SYSTEM_SETTINGS.get(sys.platform, LINUX_SETTINGS)
    defaults = env.get("QWEN_CODE_SYSTEM_DEFAULTS_PATH") or os.path.join(os.path.dirname(system),
                                                                          "system-defaults.json")
    return ([defaults] + [os.path.join(home, "settings.json") for home in homes]
            + [os.path.join(repo, ".qwen", "settings.json"), system])


def configured_dir(path, repo, env):
    """The runtime directory a settings file names, resolved as Qwen resolves
    it, or None. A relative one is taken from the repository's root, the
    working directory a session in it most often has."""
    try:
        with open(path, encoding="utf-8") as f:
            settings = json.loads(JSONC.sub(lambda m: m.group(1) or " ", f.read()))
    except (OSError, UnicodeError, ValueError):
        return None
    advanced = settings.get("advanced") if isinstance(settings, dict) else None
    value = advanced.get("runtimeOutputDir") if isinstance(advanced, dict) else None
    if not isinstance(value, str) or not value:
        return None
    value = VARIABLE.sub(lambda m: m.group(0) if (m.group(1) or m.group(2)).upper() in UNEXPANDED
                         else env.get(m.group(1) or m.group(2), m.group(0)), value)
    if value == "~" or value.startswith(("~/", "~\\")):
        # Either separator, on every platform, as Qwen splits it.
        value = os.path.join(os.path.expanduser("~"), *filter(None, re.split(r"[/\\]+", value[2:])))
    return os.path.join(repo, value)


def runtime_dirs(repo, homes, env):
    """The directories the settings files name, in their order, each once."""
    found = []
    for path in settings_files(repo, homes, env):
        directory = configured_dir(path, repo, env)
        if directory and directory not in found:
            found.append(directory)
    return found


def chat_logs(homes):
    """Every 0.4.0-and-later session file under the homes, archived ones
    included, each once, and how many directories could not be listed."""
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
            # An archived session is moved to chats/archive/, and its calls
            # were made all the same.
            chats = os.path.join(projects, project, "chats")
            for folder in (chats, os.path.join(chats, "archive")):
                try:
                    found |= {os.path.join(folder, name) for name in os.listdir(folder) if name.endswith(".jsonl")}
                except (FileNotFoundError, NotADirectoryError):
                    continue
                except OSError:
                    # The folder, or a directory above it.
                    unreadable += 1
                    break
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


def scan(repo, homes, env=None):
    """The repository's Qwen Code usage, or None when no session belongs to it
    and nothing was unreadable.

    Beside the homes, every directory a settings file names is read, not only
    the one Qwen would pick: sessions stay where they were written when the
    setting changes, and a directory holding other repositories' sessions adds
    none of them. No homes still means nothing is read."""
    repo_real = os.path.realpath(repo)
    if homes:
        seen = {os.path.realpath(home) for home in homes}
        for directory in runtime_dirs(repo, homes, os.environ if env is None else env):
            if os.path.realpath(directory) not in seen:
                seen.add(os.path.realpath(directory))
                homes = list(homes) + [directory]
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
