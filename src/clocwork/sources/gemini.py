"""Gemini CLI: one session file per conversation under
<runtime>/tmp/<project>/chats/, with sub-agent sessions nested below their
parent. The runtime directory is ~/.gemini, or ~/.cache/.gemini under the
macOS sandbox, and GEMINI_CLI_HOME stands in for the home directory.

Sessions are JSONL: a metadata record naming the project by the SHA-256 of
its root, message records, and $set updates, whose messages list is a
checkpoint repeating earlier messages. A message is written again whenever it
changes, so messages are counted once per id. Older sessions are a single
JSON document with the same metadata and a messages list. The project
directory's name comes from a registry and says nothing reliable, so the
metadata hash decides which sessions belong to a repository. The hash is of
the directory Gemini CLI was started in, so every directory the repository
tracks is a candidate, not only its root.
"""

import hashlib
import json
import os
import re
import subprocess

from clocwork import tokens
from clocwork.paths import git_env

KEY = "gemini"
LABEL = "Gemini CLI"
# Gemini CLI writes no co-author trailer; this matches the agents.VENDORS row
# for commits whose author credited Gemini by hand, and not Gemini Code
# Assist, which is a different product with no logs here.
AGENT = re.compile(r"^Gemini$")
# A session file that cannot be read, or is built in a way no Gemini CLI
# version writes (messages that are a number, say), is counted as
# unreadable rather than stopping the run. An id, hash, model or timestamp of
# the wrong type is read as missing instead.
READ_ERRORS = (OSError, TypeError, AttributeError)


def default_homes(env):
    home = env.get("GEMINI_CLI_HOME") or os.path.expanduser("~")
    return [os.path.join(home, ".gemini", "tmp"), os.path.join(home, ".cache", ".gemini", "tmp")]


def tracked_directories(repo):
    """Every directory the repository tracks at HEAD, relative to its root;
    none when it is not a repository or has no commits."""
    result = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-d", "-z", "--name-only", "HEAD"],
                            capture_output=True, text=True, env=git_env())
    return [d for d in result.stdout.split("\0") if d] if result.returncode == 0 else []


def project_hashes(repo):
    """The hashes Gemini CLI could have recorded for a session started in the
    repository or a directory it tracks: of each path as given and as real."""
    roots = {os.path.abspath(repo), os.path.realpath(repo)}
    paths = set(roots)
    for directory in tracked_directories(repo):
        paths.update(os.path.join(root, directory) for root in roots)
    return {hashlib.sha256(p.encode("utf-8")).hexdigest() for p in paths}


def session_files(homes):
    """Every session file under the homes, and how many homes could not be listed."""
    found, unreadable = [], 0
    for home in homes:
        if not os.path.isdir(home):
            continue
        try:
            projects = os.listdir(home)
        except OSError:
            unreadable += 1
            continue
        for project in projects:
            for directory, _dirs, files in os.walk(os.path.join(home, project, "chats")):
                found += [os.path.join(directory, name) for name in files if name.endswith((".jsonl", ".json"))]
    return sorted(found), unreadable


def counters(t):
    """The four archive counters from a message's tokens.

    input (promptTokenCount) includes the cached tokens. Thoughts are
    reported beside output: every recorded message has total = input +
    output + thoughts + tool. A deployment that folds them into output
    reports a total without them, and then they are not added again.
    """
    n = {k: max(0, tokens.count(t.get(k))) for k in ("input", "output", "cached", "thoughts", "tool")}
    folded = t.get("total") in (n["input"] + n["output"], n["input"] + n["output"] + n["tool"])
    return tokens.additive(input=max(0, n["input"] - n["cached"]) + n["tool"],
                           output=n["output"] + (0 if folded else n["thoughts"]),
                           cache_read=n["cached"])


def read_legacy(path, hashes):
    with open(path, encoding="utf-8", errors="replace") as f:
        try:
            doc = json.load(f)
        except ValueError:
            return None, 1
    if not isinstance(doc, dict) or tokens.text(doc.get("projectHash")) not in hashes:
        return None, 0
    return [m for m in doc.get("messages") or [] if isinstance(m, dict)], 0


def read_session(path, hashes):
    """(messages, malformed lines) for one session file; messages is None
    when the file belongs to another project or names none."""
    if path.endswith(".json"):
        return read_legacy(path, hashes)
    messages, matched, malformed = [], None, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"tokens"' not in line and '"projectHash"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(rec, dict):
                continue
            if matched is None and "projectHash" in rec and "sessionId" in rec:
                matched = tokens.text(rec["projectHash"]) in hashes
                if not matched:
                    return None, malformed
            elif isinstance(rec.get("$set"), dict):
                messages += [m for m in rec["$set"].get("messages") or [] if isinstance(m, dict)]
            elif "id" in rec:
                messages.append(rec)
    return (messages if matched else None), malformed


def scan(repo, homes, kind="gemini"):
    """The repository's Gemini CLI usage, or None when no session belongs to it
    and nothing was unreadable. `kind` is the type a model's message carries:
    Qwen Code's first releases wrote this same format with "qwen" there."""
    hashes = project_hashes(repo)
    files, skipped = session_files(homes)
    latest, found, malformed = {}, False, 0
    for path in files:
        try:
            messages, bad = read_session(path, hashes)
        except READ_ERRORS:
            skipped += 1
            continue
        malformed += bad
        if messages is None:
            continue
        found = True
        for m in messages:
            # Later writes of a message carry the same tokens or ones that
            # arrived late; a write without tokens never replaces one with.
            if m.get("type") == kind and tokens.text(m.get("id")) and isinstance(m.get("tokens"), dict):
                latest[m["id"]] = m
    if not found and not skipped:
        return None
    days = {}
    for m in latest.values():
        date = tokens.day(m.get("timestamp"))
        c = counters(m["tokens"])
        if date and any(c.values()):
            tokens.record(days, date, m.get("model"), c)
    return tokens.ScanResult(days, malformed, skipped)
