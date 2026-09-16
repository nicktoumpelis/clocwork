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
metadata hash decides which sessions belong to a repository.
"""

import hashlib
import json
import os
import re

from clocwork import tokens

KEY = "gemini"
LABEL = "Gemini CLI"
# Gemini CLI writes no co-author trailer; this matches the agents.VENDORS row
# for commits whose author credited Gemini by hand.
AGENT = re.compile(r"^Gemini\b")


def default_homes(env):
    home = env.get("GEMINI_CLI_HOME") or os.path.expanduser("~")
    return [os.path.join(home, ".gemini", "tmp"), os.path.join(home, ".cache", ".gemini", "tmp")]


def project_hashes(repo):
    """The hashes Gemini CLI could have recorded for the repository: of its
    path as given and of its real path."""
    return {hashlib.sha256(p.encode("utf-8")).hexdigest()
            for p in (os.path.abspath(repo), os.path.realpath(repo))}


def session_files(homes):
    found = []
    for home in homes:
        if not os.path.isdir(home):
            continue
        for project in os.listdir(home):
            for directory, _dirs, files in os.walk(os.path.join(home, project, "chats")):
                found += [os.path.join(directory, name) for name in files if name.endswith((".jsonl", ".json"))]
    return sorted(found)


def counters(t):
    """The four archive counters from a message's tokens.

    input (promptTokenCount) includes the cached tokens. Thoughts are
    reported beside output: every recorded message has total = input +
    output + thoughts + tool. A deployment that folds them into output
    reports a total without them, and then they are not added again.
    """
    n = {k: max(0, t.get(k) or 0) for k in ("input", "output", "cached", "thoughts", "tool")}
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
    if not isinstance(doc, dict) or doc.get("projectHash") not in hashes:
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
                matched = rec["projectHash"] in hashes
                if not matched:
                    return None, malformed
            elif isinstance(rec.get("$set"), dict):
                messages += [m for m in rec["$set"].get("messages") or [] if isinstance(m, dict)]
            elif "id" in rec:
                messages.append(rec)
    return (messages if matched else None), malformed


def scan(repo, homes):
    """The repository's Gemini CLI usage, or None when no session belongs to it."""
    hashes = project_hashes(repo)
    latest, found, malformed, skipped = {}, False, 0, 0
    for path in session_files(homes):
        try:
            messages, bad = read_session(path, hashes)
        except OSError:
            skipped += 1
            continue
        malformed += bad
        if messages is None:
            continue
        found = True
        for m in messages:
            # Later writes of a message carry the same tokens or ones that
            # arrived late; a write without tokens never replaces one with.
            if m.get("type") == "gemini" and m.get("id") and isinstance(m.get("tokens"), dict):
                latest[m["id"]] = m
    if not found:
        return None
    days = {}
    for m in latest.values():
        date = (m.get("timestamp") or "")[:10]
        c = counters(m["tokens"])
        if date and any(c.values()):
            tokens.record(days, date, m.get("model"), c)
    return tokens.ScanResult(days, malformed, skipped)
