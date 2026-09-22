"""Antigravity: Google's coding agent, whose CLI (agy) keeps each conversation
in its own SQLite database of protobuf records, under
~/.gemini/antigravity-cli/conversations/<conversation id>.db.

Every model call is recorded twice: in the step that holds its reply (the
step's metadata, field 9) and in a gen_metadata row (data field 1.4), both
carrying the call's response id (field 11), which is what makes them one
call. The usage message's fields, as checked against agy 1.2.8's own
reported usage: 2 is the input, 3 the output with the thinking already
in it, 9 the thinking and 10 the visible reply (9 + 10 = 3). 4 and 5 are the
cache write and read, which no recorded call used; the read is taken to sit
inside the input, as it does in Gemini's own API, and that is unconfirmed.
The model's name is in the gen_metadata row (field 1.19); a step carries
only its numeric id (field 1). A step's metadata also holds the time it was
created (field 1), which dates the call; a gen_metadata row has no time of
its own, so one without a step takes the trajectory's (field 2 of
trajectory_metadata_blob).

A print-mode conversation's database holds no directory at all (an
interactive one's names its workspace among its tool calls and trajectory,
but not in one place a reader can rely on). conversation_summaries.db
names the workspace of an interactive conversation (workspace_uris, a JSON
list of file:// URIs); a print-mode one (agy -p) has none there, and only the
CLI log of the run that created it says where it ran: `workspaceDirs=[...]`,
then `Created conversation <id>`. The summary is taken first, then the log.
A conversation that neither places is held back rather than guessed at.

The IDE's older conversations are encrypted .pb files, and are not read.
"""

import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from clocwork import tokens

KEY = "antigravity"
LABEL = "Antigravity"
# agents.VENDORS reports every trailer that names Antigravity as
# "Antigravity"; agy itself writes none.
AGENT = re.compile(r"^Antigravity$")
SKIPPED = "damaged, locked, in a directory this user cannot write, or not a conversation database this reader knows"
MALFORMED_UNIT = "records"
HELD = ("no workspace recorded for them, in a summary or in a CLI log still on disk,"
        " so no repository can claim them; counted across this machine")
READ_ERRORS = (OSError, ValueError, TypeError, sqlite3.Error)
# The directories Antigravity keeps its data in, under ~/.gemini: the CLI's,
# the IDE's (Antigravity 1.2.3 writes conversation_summaries.db there), and
# the IDE's other names other readers list. A directory holding none of the
# files below adds nothing.
ROOTS = ("antigravity-cli", "antigravity", "antigravity-ide", "antigravity-backup")
WORKSPACE = re.compile(r"workspaceDirs=\[([^\]\n]*)\]")
CREATED = re.compile(r"Created conversation ([0-9A-Za-z-]+)")


def default_homes(env):
    base = os.path.join(os.path.expanduser("~"), ".gemini")
    return [os.path.join(base, root) for root in ROOTS]


def varint(blob, i):
    n = shift = 0
    while True:
        if i >= len(blob) or shift > 63:
            raise ValueError("truncated varint")
        byte = blob[i]
        i += 1
        n |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return n, i


def message(blob):
    """A protobuf message's fields, {number: value}, the last one written
    winning: a varint as an int, a length-delimited field as bytes, the fixed
    widths as ints. Raises ValueError on anything that is not one."""
    if not isinstance(blob, bytes):
        raise ValueError("not a message")
    fields, i = {}, 0
    while i < len(blob):
        key, i = varint(blob, i)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("field 0")
        if wire == 0:
            value, i = varint(blob, i)
        elif wire in (1, 5):
            width = 8 if wire == 1 else 4
            value, i = int.from_bytes(blob[i:i + width], "little"), i + width
        elif wire == 2:
            size, i = varint(blob, i)
            value, i = blob[i:i + size], i + size
        else:
            raise ValueError(f"wire type {wire}")
        if i > len(blob):
            raise ValueError("truncated field")
        fields[number] = value
    return fields


def sub(fields, number):
    """A nested message, or {} when the field is missing."""
    value = fields.get(number)
    return message(value) if isinstance(value, bytes) else {}


def string(fields, number):
    value = fields.get(number)
    try:
        return tokens.text(value.decode("utf-8")) if isinstance(value, bytes) else None
    except UnicodeError:
        return None


def when(fields):
    """The UTC date of a {seconds, nanos} time, or ''."""
    seconds = fields.get(1)
    if not isinstance(seconds, int) or seconds <= 0:
        return ""
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        # agy writes u64::MAX as a sentinel in time-shaped fields.
        return ""


def is_usage(usage):
    """Whether a decoded field is a usage message: one with a count in it."""
    return any(isinstance(usage.get(n), int) for n in (2, 3, 4, 5))


def counters(usage):
    prompt, cached = tokens.count(usage.get(2)), tokens.count(usage.get(5))
    return tokens.additive(input=max(0, prompt - cached), output=usage.get(3),
                           cache_read=cached, cache_write=usage.get(4))


def open_read_only(path):
    uri = "file:" + urllib.request.pathname2url(os.path.abspath(path)) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def read_conversation(path):
    """(calls, malformed) from one conversation database, calls being
    {key: (date, model, usage fields)}, keyed by response id. Raises
    READ_ERRORS for a file that is not a conversation database."""
    conn = open_read_only(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables & {"steps", "gen_metadata"}:
            raise ValueError("not a conversation database")
        blobs = {t: conn.execute(f"SELECT idx, {c} FROM {t} ORDER BY idx").fetchall()
                 for t, c in (("steps", "metadata"), ("gen_metadata", "data")) if t in tables}
        trajectory = (conn.execute("SELECT data FROM trajectory_metadata_blob").fetchall()
                      if "trajectory_metadata_blob" in tables else [])
    finally:
        conn.close()
    malformed, dated, generated, names = 0, {}, {}, {}
    for idx, blob in blobs.get("steps", ()):
        try:
            fields = message(blob) if blob else {}
            usage = sub(fields, 9)
            if is_usage(usage):
                key = string(usage, 11) or f"{path}:step:{idx}"
                dated[key] = (when(sub(fields, 1)), usage)
        except ValueError:
            malformed += 1
    for idx, blob in blobs.get("gen_metadata", ()):
        try:
            generation = sub(message(blob) if blob else {}, 1)
            usage = sub(generation, 4)
            if is_usage(usage):
                model = string(generation, 19)
                generated[string(usage, 11) or f"{path}:gen:{idx}"] = (model, usage)
                if model and isinstance(usage.get(1), int):
                    names.setdefault(usage[1], model)
        except ValueError:
            malformed += 1
    started = ""
    for (blob,) in trajectory:
        try:
            started = started or when(sub(message(blob) if blob else {}, 2))
        except ValueError:
            malformed += 1
    calls = {}
    for key in list(dated) + [k for k in generated if k not in dated]:
        date, usage = dated.get(key) or (started, generated[key][1])
        model = generated.get(key, (None,))[0] or names.get(usage.get(1))
        calls[key] = (date, model, usage)
    return calls, malformed


def summaries(home):
    """{conversation id: its first workspace path} from the summaries
    database; a conversation it records without one maps to None."""
    path = os.path.join(home, "conversation_summaries.db")
    if not os.path.isfile(path):
        return {}
    placed = {}
    try:
        conn = open_read_only(path)
        try:
            rows = conn.execute("SELECT conversation_id, workspace_uris FROM conversation_summaries").fetchall()
        finally:
            conn.close()
    except READ_ERRORS:
        return {}
    for cid, uris in rows:
        placed[cid] = workspace_of(uris)
    return placed


def workspace_of(uris):
    """The first workspace a summary's workspace_uris names, as a local
    path, or None: for no list, a list with nothing usable first, or a URI
    that names another host or will not parse."""
    try:
        uris = json.loads(uris) if isinstance(uris, str) and uris else []
        first = uris[0] if isinstance(uris, list) and uris else None
        parsed = urllib.parse.urlparse(first) if isinstance(first, str) else None
        local = parsed and parsed.scheme == "file" and parsed.netloc in ("", "localhost") and parsed.path
        return urllib.request.url2pathname(parsed.path) if local else None
    except ValueError:
        return None


def logged(home):
    """{conversation id: the workspace text of the run that created it},
    from the CLI logs. agy prints a run's directories space-separated, so
    the text is the first directory with any --add-dir ones after it."""
    folder = os.path.join(home, "log")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return {}
    placed = {}
    for name in names:
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                workspace = None
                for line in f:
                    match = WORKSPACE.search(line)
                    if match:
                        workspace = match.group(1)
                        continue
                    match = CREATED.search(line)
                    if match and workspace:
                        placed.setdefault(match.group(1), workspace)
        except OSError:
            continue
    return placed


def inside(path, repo_real):
    try:
        real = os.path.realpath(path)
    except ValueError:
        # A NUL byte, from a damaged log or a %00 in a URI: no directory.
        return False
    return real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep)


def log_directory(workspace):
    """The first directory a log's workspace text names. agy prints a run's
    directories space-separated, so nothing marks where one with a space in
    its name ends. The text can only split where a space is followed by an
    absolute path, as the next directory's is: the whole text is taken when
    it is a directory, else the longest part before such a split that is one.
    When none is, as when the directories are gone, the whole text is all
    there is -- which is why "MyApp 2", deleted, never reads as "MyApp"."""
    heads = [workspace] + [workspace[:i] for i in range(len(workspace) - 1, 0, -1)
                           if workspace[i] == " " and workspace[i + 1:].startswith(os.sep)]
    return next((head for head in heads if os.path.isdir(head)), workspace)


def in_log(workspace, repo_real):
    """Whether a log's workspace text puts a run in the repository. A
    relative path is none: agy logs absolute ones."""
    directory = log_directory(workspace)
    return os.path.isabs(directory) and inside(directory, repo_real)


def scan(repo, homes):
    """The repository's Antigravity usage, or None when no conversation
    belongs to it and nothing was unreadable."""
    repo_real = os.path.realpath(repo)
    seen, calls, malformed, skipped, held, belonged = set(), {}, 0, 0, 0, False
    for home in homes:
        real = os.path.realpath(home)
        folder = os.path.join(home, "conversations")
        if real in seen or not os.path.isdir(folder):
            continue
        seen.add(real)
        try:
            names = sorted(n for n in os.listdir(folder) if n.endswith(".db"))
        except OSError:
            skipped += 1
            continue
        summary, log = summaries(home), None
        for name in names:
            cid = name[:-3]
            workspace = summary.get(cid)
            if workspace:
                mine = inside(workspace, repo_real)
            else:
                log = logged(home) if log is None else log
                if cid not in log:
                    held += 1
                    continue
                mine = in_log(log[cid], repo_real)
            if not mine:
                continue
            belonged = True
            try:
                found, bad = read_conversation(os.path.join(folder, name))
            except READ_ERRORS:
                skipped += 1
                continue
            malformed += bad
            calls.update(found)
    if not belonged and not skipped:
        return None
    days = {}
    for date, model, usage in calls.values():
        if not date:
            malformed += 1
            continue
        counts = counters(usage)
        if any(counts.values()):
            tokens.record(days, date, model, counts)
    return tokens.ScanResult(days, malformed, skipped, held)
