"""Codex CLI: one JSONL rollout per session under $CODEX_HOME/sessions/YYYY/MM/DD/,
moved flat into archived_sessions/ when archived, and compressed to
.jsonl.zst once cold.

Two usage formats exist. From CLI 0.153.4 every model response writes a
token_usage_record with that response's usage and id; earlier versions write
only token_count events, each carrying the session's running total and the
increment just added to it. A session resumed across the upgrade holds both:
the older events first, then records.

A forked session starts with a copy of its parent's history, token_count
events included and re-timestamped, and those copies must not count twice.
They are recognised two ways. The parent's own file holds the same
(total, increment) pairs; unrelated sessions that open with the same prompt
report identical pairs too, so only the parent's pairs count as copies.
Without the parent's file (deleted, or compressed on an older Python), the
turns tell: Codex ids are UUIDv7, ordered by creation time, so the copied
turns sort before the fork's own id and the fork's own turns after it. The
public recordings in tests/fixtures/codex hold both formats, sub-agents and
a fork.
"""

import json
import os
import re
import subprocess

from clocwork import paths, tokens

try:
    from compression import zstd
except ImportError:             # before Python 3.14
    zstd = None

KEY = "codex"
LABEL = "Codex CLI"
# Codex asks for "Co-authored-by: Codex <noreply@openai.com>" on its commits.
AGENT = re.compile(r"^Codex\b")
SKIPPED = "damaged, or compressed and this Python is older than 3.14"

# A file that cannot be opened, or is built in a way no Codex version writes
# (a payload or usage that is not an object), is counted as unreadable rather
# than stopping the run. An id, model or timestamp of the wrong type is read
# as missing instead. A missing response id only stops that response being
# deduplicated; a missing session id stops the whole file being deduplicated
# against other copies of the session.
READ_ERRORS = (OSError, EOFError, UnicodeError, TypeError, AttributeError) + ((zstd.ZstdError,) if zstd else ())
# Only these lines matter; messages, tool calls and other events are skipped
# before they are parsed.
WANTED = ('"turn_context"', '"token_usage_record"', '"token_count"')
# A full commit hash, SHA-1 or SHA-256; git is asked about nothing else.
COMMIT = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?")
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


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


def commit_lookup(repo):
    """A test of whether a full hash names a commit in the repository,
    asking git once per hash.

    The hashes asked about are mostly another repository's, so a partial
    clone must not fetch them from its remote, and nothing may wait on a
    prompt. GIT_NO_LAZY_FETCH (git 2.44+) skips the fetch; before that,
    protocol.allow=never makes it fail before connecting, so no ssh
    passphrase or credential prompt can appear either.
    """
    known = {}
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")

    def lookup(sha):
        if sha not in known:
            known[sha] = bool(COMMIT.fullmatch(sha)) and subprocess.run(
                ["git", "-c", "protocol.allow=never", "-C", repo, "cat-file", "-e", sha + "^{commit}"],
                stdin=subprocess.DEVNULL, capture_output=True, env=env).returncode == 0
        return known[sha]
    return lookup


def ran_inside(meta, repo_real):
    """Whether the session's working directory is the repository's or below it."""
    cwd = tokens.text(meta.get("cwd"))
    if cwd is None:
        return False
    real = os.path.realpath(cwd)
    return real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep)


def belongs(meta, repo_real, remote, known_commit):
    """Whether a session ran in the repository.

    When both name a remote, the same remote decides, as
    paths.check_identity does, so a session from any clone counts. A session
    that recorded another remote still belongs when it ran in the
    repository's directory from one of the repository's commits: the
    repository was renamed or moved since, while a different repository
    cloned to the same path shares none of its commits. Without two remotes
    to compare, the working directory decides.
    """
    git = meta.get("git") or {}
    url = tokens.text(git.get("repository_url"))
    if remote and url:
        parsed = paths.parse_remote(url)
        if parsed is not None and f"{parsed[0]}/{parsed[1]}".lower() == remote.lower():
            return True
        commit = tokens.text(git.get("commit_hash"))
        return commit is not None and ran_inside(meta, repo_real) and known_commit(commit)
    return ran_inside(meta, repo_real)


def counts(usage):
    return tokens.inclusive(usage.get("input_tokens"), usage.get("output_tokens"),
                            usage.get("cached_input_tokens"), usage.get("cache_write_input_tokens"))


def uuid7(value):
    return value if isinstance(value, str) and UUID7.match(value) else None


def read_session(lines, repo_real, remote, known_commit):
    """(session, malformed lines) for one rollout, or (None, n) when it is
    not the repository's or does not open with its session_meta.

    A session is {"id", "forked_from", "records", "events", "before_records"}:
    records are (response_id, date, model, counts) from token_usage_record
    lines; events are (pair, date, model, counts, inherited) from token_count
    lines whose running total moved, where inherited says a fork's own turns
    had not begun yet; before_records is how many events precede the first
    record.
    """
    first = next(lines, "")
    if not first.strip():
        return None, 0              # a rollout Codex has only just created
    try:
        head = json.loads(first)
    except ValueError:
        return None, 1
    if not isinstance(head, dict) or head.get("type") != "session_meta":
        return None, 1
    meta = head.get("payload") or {}
    if not belongs(meta, repo_real, remote, known_commit):
        return None, 0
    session = {"id": tokens.text(meta.get("id")), "forked_from": tokens.text(meta.get("forked_from_id")),
               "records": [], "events": [], "before_records": None}
    own = uuid7(session["id"]) if session["forked_from"] else None
    turn_models, model, previous, own_turns, malformed = {}, None, None, False, 0
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
        date = tokens.day(rec.get("timestamp"))
        if kind == "turn_context":
            model = tokens.text(payload.get("model")) or model
            turn_id = tokens.text(payload.get("turn_id"))
            if turn_id:
                turn_models[turn_id] = tokens.text(payload.get("model"))
                if own and (uuid7(turn_id) or "") > own:
                    own_turns = True
        elif kind == "token_usage_record":
            if not session["records"]:
                session["before_records"] = len(session["events"])
            session["records"].append((tokens.text(payload.get("response_id")), date,
                                       turn_models.get(tokens.text(payload.get("turn_id"))) or model,
                                       counts(payload.get("usage") or {})))
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            total, last = info.get("total_token_usage"), info.get("last_token_usage")
            if not total or not last or total == previous:
                continue            # no usage yet, or the running total repeated
            previous = total
            session["events"].append((json.dumps([total, last], sort_keys=True), date, model, counts(last),
                                      bool(own) and not own_turns))
    return session, malformed


def replayed(session, by_id):
    """How many of a session's leading token_count events were copied from
    its parent when it was forked: those the parent's file also holds, or,
    without that file, those written before the fork's own first turn. A
    fork's file holds its whole inherited history, so one generation is
    enough."""
    parent = by_id.get(session["forked_from"])
    inherited = {pair for pair, *_rest in parent["events"]} if parent else set()
    n = 0
    events = session["events"]
    while n < len(events) and (events[n][0] in inherited or (parent is None and events[n][4])):
        n += 1
    return n


def scan(repo, homes):
    """The repository's Codex usage, or None when no rollout in the homes
    belongs to it and none was unreadable."""
    repo_real = os.path.realpath(repo)
    remote = paths.remote_key(repo) if os.path.isdir(repo) else None
    known_commit = commit_lookup(repo)
    found, malformed, skipped = {}, 0, 0
    for path in rollouts(homes):
        compressed = path.endswith(".zst")
        if compressed and zstd is None:
            skipped += 1
            continue
        try:
            with (zstd.open if compressed else open)(path, "rt", encoding="utf-8", errors="replace") as f:
                session, bad = read_session(iter(f), repo_real, remote, known_commit)
        except READ_ERRORS:
            skipped += 1
            continue
        malformed += bad
        if session is None:
            continue
        # The same session can sit in two places (sessions/ and
        # archived_sessions/, or plain and compressed); the fuller copy wins.
        key = session["id"] or path
        kept = found.get(key)
        if kept is None or (len(session["records"]) + len(session["events"])
                            > len(kept["records"]) + len(kept["events"])):
            found[key] = session
    if not found and not skipped:
        return None

    days, responses = {}, set()
    sessions = list(found.values())
    by_id = {s["id"]: s for s in sessions if s["id"]}

    def add(date, model, c):
        # An all-zero record is a context-window fill, not a response.
        if date and any(c.values()):
            tokens.record(days, date, model, c)

    for s in sessions:
        for response_id, date, model, c in s["records"]:
            if response_id is not None:
                if response_id in responses:
                    continue
                responses.add(response_id)
            add(date, model, c)
        # With records, only the events written before them are usage the
        # records do not already cover.
        end = s["before_records"] if s["records"] else len(s["events"])
        for _pair, date, model, c, _inherited in s["events"][replayed(s, by_id):end]:
            add(date, model, c)
    return tokens.ScanResult(days, malformed, skipped)
