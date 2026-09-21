"""OpenCode: sessions in a SQLite database, or in files for older releases,
under $XDG_DATA_HOME/opencode (~/.local/share/opencode on every OS).

**Four storage generations**, and a store can hold several at once, because
both migrations copy and delete nothing:

  J0  v0.1.0-v0.5.29    project/<root with separators as "-">/storage/
                        session/{info,message,part}/...
  J1  v0.6.0-v1.1.65    storage/{project,session,message,part}/...
  S1  v1.2.0 on         opencode*.db: tables project, session, message, part
  S2  v1.14.34 on       the same database's session_message table

A record read from two generations is the same record: the migrations keep
message and part ids, and a store stops changing once it is migrated. So
records are merged by id, the newest generation read last.

**One record is one model call.** Each call writes a "step-finish" part
carrying its own tokens, while the assistant message's tokens are
*overwritten* by the latest step. Before v0.15.0 a message could hold up to
1,000 steps, so its tokens under-report; the parts are what is counted, and
the message only when it has no step-finish part.

**What the counters exclude is not one rule.** OpenCode has stored the
prompt count four different ways and the output count two, and *where
reasoning sits was never a property of the release*: it is the provider's.
The v5 SDK put OpenAI's reasoning inside the output and Google's beside it,
so one release writes both shapes depending on which model ran - the
recordings show v1.2.15 storing it outside and v1.2.17 inside - and a v1.3.13
recording, on the v6 SDK, has Google's inside too. From v1.3.16 OpenCode
subtracts it itself, for every provider, as a v1.17.20 OpenAI recording shows.

So `counters()` asks the record before it asks anything else: when `total`
is there, `total == input + output + cache` means reasoning is already
inside the output and `total == that + reasoning` means it is not. That is
the only evidence which does not depend on knowing the release, and it
settles every recorded record that has any reasoning. A record without a
`total` - the key arrived in v1.1.57, and the v1.17.9 rows do not carry it -
falls back to the version, and then to the provider for the releases where
the provider decided. So does a record from the two windows below whose
input still holds the cache, because then `input + output + cache` counts
the cache twice and neither reading can match.

The prompt count is version-keyed, because nothing in a record reveals it:
before v1.0.62 it held cache reads for every provider but Anthropic, and in
v1.3.4 and v1.3.5 it held them *only* for Anthropic, which the v6 SDK had
just changed. Neither of those two windows appears in any public recording,
so their fixtures are hand-written and say so. A cache write does appear in
one: v1.17.20 Anthropic records, from 36 to 51,300 tokens written, each
counted in full beside the input.

**A fork copies its messages and parts under new ids**, keeping the original
`time.created`. Ids encode their own creation time, so a record whose id was
minted more than a minute after the message it belongs to is a copy, and is
skipped rather than counted twice.

**A session belongs to the repository** by project id or by directory. The
project id is the SHA-1 of "git-remote:" + host/path of origin, which is the
same string paths.remote_key builds, so any clone or worktree of the same
remote counts. Releases before v1.15.11 used the repository's root commit
instead, and a store can still hold those, so a session whose directory is
the repository's is accepted when its project id names no other repository.
"""

import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from collections import namedtuple

from clocwork import paths, tokens
from clocwork.sources.codex import commit_lookup

KEY = "opencode"
LABEL = "OpenCode"
# OpenCode writes no co-author trailer of its own (it did until v0.4.19);
# this matches the agents.VENDORS row for the trailers people add, and never
# "OpenCode GitHub agent", whose logs stay on the GitHub runner.
AGENT = re.compile(r"^OpenCode$")
SKIPPED = "damaged, or a database this Python's sqlite3 cannot open"
# What a damaged record is here: a row of the database, not a line of a log.
MALFORMED_UNIT = "rows"

# A store written by a version this reader does not understand, or damaged,
# is counted rather than raising: one unreadable session must not stop a run.
READ_ERRORS = (OSError, ValueError, TypeError, AttributeError, sqlite3.Error)

# Ids are "<prefix>_" + 12 hex digits of (time_ms << 12 | counter), then
# random characters (packages/schema/src/identifier.ts).
ID_TIME = re.compile(r"^[a-zA-Z]+_([0-9a-fA-F]{12})")
ID_BITS = 48
ID_COUNTER_BITS = 12
# A fork's copies are minted long after the messages they copy. A minute of
# slack covers the few milliseconds real ids drift from their message's
# recorded time, and a clock that is not quite monotonic.
FORK_SLACK_MS = 60_000

# The providers whose API reports cache reads and writes beside an uncached
# prompt, so OpenCode never had to subtract them.
ANTHROPIC_PROVIDERS = ("anthropic", "amazon-bedrock", "google-vertex-anthropic")
# The providers whose AI SDK v5 mapping reported thoughts outside the output.
GOOGLE_PROVIDERS = ("google", "google-vertex")

# Where each counter rule starts (see the module docstring's era table).
ERA_B = (1, 0, 62)    # uncached input for non-Anthropic providers
ERA_C = (1, 3, 4)     # AI SDK v6: Anthropic input turns inclusive
ERA_D = (1, 3, 6)     # uncached input for every provider
ERA_E = (1, 3, 16)    # reasoning no longer inside output
# The release the session_message table arrived in, which is the oldest
# counter rule a row in it can have been written under.
V2_TABLE_FROM = (1, 14, 34)

# What a fork of OpenCode changed about where its store is and how its
# records are read. Kilo Code is one: same tables, same message JSON, same
# project-id hash, four things moved.
#
#   databases    the names its channel databases take, in glob form,
#                **oldest name first**: where two of them hold the same
#                record, the one read later is the copy that is kept
#   cache_name   the file it caches a project id in, under the git directory
#   floor        the oldest counter era one of its records can have been
#                written under; () for OpenCode, which wrote every era
#   file_stores  whether the JSON generations that predate the database can
#                sit in its data directory
Store = namedtuple("Store", "databases cache_name floor file_stores")
OPENCODE = Store(("opencode*.db",), "opencode", (), True)
# Kilo's own version numbers say nothing about which era wrote a record.
# Its releases run v1.0.9 (2025-11-01) to v1.0.25, then jump to v7.0.26,
# so they span every era here and the earliest of them predate even ERA_B -
# while `version_of` reads a 7.x as above all of them and the literal
# "local", which a build from source records, as below all of them.
#
# A record's own `total` is therefore the only evidence, and counters()
# asks it first. Where a record has none, the floor lands the record on
# ERA_B, which input_cache() reads without subtracting: era A's rule needs
# a version below ERA_B or none at all, and era C's needs one in
# [ERA_C, ERA_D). Era A is the rule a version-less record would otherwise
# reach, and the only one it can reach.
#
# Both directions are wrong, by exactly the cache read, and the floor picks
# which. Read a post-era-A record under era A and the cache read is taken
# out of an input that never held it, so the prompt is understated. Read a
# genuine era-A record under era B and the cache read stays in `input`
# while `cache_read` reports it too -- those are separate archive counters,
# so a sum over them counts it twice (1,500 rather than 1,100, for a
# 1,000-token prompt with 400 served from cache). The floor prefers the
# over-count, because it leaves the tokens visible in a labelled counter
# instead of silently deleting prompt tokens, and because era A's window is
# the fork's first weeks: Kilo v1.0.9 shipped 2025-11-01 and upstream
# ERA_B landed 2025-11-13. How far past that a Kilo release still vendored
# era-A semantics is exactly what is not known.
#
# Which OpenCode release each Kilo version carried would settle it, and
# Kilo's sync commits name them ("kilo compat for v1.14.29"), but that is a
# mapping nobody has built yet.
#
# `opencode-<channel>.db` comes first because it is the name Kilo wrote
# before its rename, and its copy of a record must give way to the current
# one. A plain `opencode.db` here is not Kilo's: the fork renamed the data
# directory as well, so a store from before the rename sits in OpenCode's
# own directory, where its own reader owns it.
#
# Kilo does read the file generations. Its database arrived in v7.0.26; up
# to v1.0.25 it shipped OpenCode's JSON store, already writing to its own
# directory (`const app = "kilo"` is there at v1.0.25), and that release
# carries the J0-to-J1 migration, so both layouts can sit in it.
KILO = Store(("opencode-*.db", "kilo*.db"), "kilo", ERA_B, True)

# One model call. `key` is the part or message id the record was read under,
# which the migrations preserve, so the same call read from two generations
# merges instead of counting twice. `session` is a session id.
Record = namedtuple("Record", "key session message_id time_ms provider model tokens version v2",
                    defaults=((), False))


def default_homes(env):
    """OpenCode's data directory, plus the database OPENCODE_DB names.

    xdg-basedir does not look at the platform, so the directory is
    ~/.local/share/opencode on macOS and Windows as well, and OpenCode has no
    variable of its own for it. A home that is a file is read as a database,
    which is how OPENCODE_DB is followed.
    """
    data = env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    homes = [os.path.join(data, "opencode")]
    db = tokens.text(env.get("OPENCODE_DB"))
    if db and db != ":memory:":
        homes.append(db if os.path.isabs(db) else os.path.join(homes[0], db))
    return homes


def version_of(value):
    """A version as comparable numbers, or () when it is not one. OpenCode's
    tags jump from v1.4 to v1.14, so versions are compared as numbers and
    never as text."""
    text = tokens.text(value)
    if not text:
        return ()
    parts = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(p) for p in parts[:3]) if parts else ()


def id_time_ms(value):
    """The creation times an id could encode, newest-first reading and its
    descending form, or () for an id this scheme does not explain.

    OpenCode mints descending ids as the complement of ascending ones. Both
    readings are returned because a wrong reading here would drop a real
    record as a fork's copy.
    """
    m = ID_TIME.match(tokens.text(value) or "")
    if not m:
        return ()
    raw = int(m.group(1), 16)
    return (raw >> ID_COUNTER_BITS, ((1 << ID_BITS) - 1 - raw) >> ID_COUNTER_BITS)


def fork_copy(message_id, created_ms):
    """Whether a message is a fork's copy: its id was minted well after the
    time it records. Only the low bits of the time are in the id, so the
    comparison wraps, and an id that explains itself either way is kept."""
    created = tokens.count(created_ms)
    if created <= 0:
        return False
    modulus = 1 << (ID_BITS - ID_COUNTER_BITS)
    for minted in id_time_ms(message_id):
        gap = (minted - created) % modulus
        if min(gap, modulus - gap) <= FORK_SLACK_MS:
            return False
    return bool(id_time_ms(message_id))


def model_name(model):
    """The model's own name, without the gateway path in front of it: an
    OpenRouter id is `openrouter/anthropic/claude-sonnet-4.5`, and what the
    API behaves like is decided by the last part."""
    return (tokens.text(model) or "").rsplit("/", 1)[-1]


def anthropic_like(provider, model):
    """Whether the call went to an Anthropic-shaped API, whatever routed it."""
    return provider in ANTHROPIC_PROVIDERS or model_name(model).startswith("claude-")


def google_like(provider, model):
    return provider in GOOGLE_PROVIDERS or model_name(model).startswith("gemini")


def reasoning_outside(t, provider, model, version, base, reasoning):
    """Whether `tokens.reasoning` is counted outside `tokens.output`.

    The record's own `total` settles it when there is one, which is the only
    evidence that does not depend on knowing the release - unless the input
    still holds the cache reads, in which case `base` counts them twice and
    neither reading can match. Then, as for a record with no `total` at all,
    the version decides, and before v1.3.16 the provider did: the v5 SDK put
    Google's thoughts outside the output and OpenAI's inside.
    """
    total = tokens.count(t.get("total"))
    if total and reasoning:
        if total == base + reasoning:
            return True
        if total == base:
            return False
    if version >= ERA_E:
        return True
    return google_like(provider, model)


def input_cache(t, provider, model, version, i, cr, cw):
    """What `tokens.input` still contains of the cache: (read, write).

    Era C (v1.3.4, v1.3.5) stored an inclusive input for Anthropic-shaped
    providers, because the v6 SDK started including cache there while
    OpenCode still skipped subtracting it. Era A (before v1.0.62) stored the
    prompt as the SDK gave it, which for every provider but Anthropic
    included cache reads. An input smaller than the cache read cannot be
    inclusive, so it is read as uncached.
    """
    if ERA_C <= version < ERA_D and anthropic_like(provider, model):
        return (cr, cw) if i >= cr + cw else (0, 0)
    # A record with no version at all: only one that also has no `total` can
    # predate v1.1.57, so only that one is read as era A. An empty version
    # compares below every era, hence the explicit `version and`.
    unversioned = not version and not tokens.count(t.get("total"))
    if ((version and version < ERA_B) or unversioned) and not anthropic_like(provider, model):
        return (cr, 0) if i >= cr else (0, 0)
    return 0, 0


def counters(t, provider, model, version):
    """The four archive counters from one record's tokens."""
    i, o, r = (tokens.count(t.get(k)) for k in ("input", "output", "reasoning"))
    cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
    cr, cw = tokens.count(cache.get("read")), tokens.count(cache.get("write"))
    counted_read, counted_write = input_cache(t, provider, model, version, i, cr, cw)
    base = i + o + cr + cw
    outside = reasoning_outside(t, provider, model, version, base, r)
    return tokens.additive(input=i - counted_read - counted_write,
                           output=o + (r if outside else 0),
                           cache_read=cr, cache_write=cw)


def message_records(session, message_id, data, parts):
    """Every record one assistant message contributes: its step-finish parts,
    or the message itself when it has none."""
    if (data.get("role") or "assistant") != "assistant":
        return []
    t = data.get("time") if isinstance(data.get("time"), dict) else {}
    created = tokens.count(t.get("created"))
    if fork_copy(message_id, created):
        return []
    provider, model = tokens.text(data.get("providerID")), tokens.text(data.get("modelID"))
    common = dict(session=session, message_id=message_id, time_ms=created,
                  provider=provider, model=model)
    found = [Record(key=part_id, tokens=usage,
                    **dict(common, provider=step_provider or provider, model=step_name or model))
             for part_id, usage, (step_provider, step_name) in parts if isinstance(usage, dict)]
    if found:
        return found
    usage = data.get("tokens")
    return [Record(key=message_id, tokens=usage, **common)] if isinstance(usage, dict) else []


def step_tokens(data):
    """The tokens of a step-finish part, or None for any other part."""
    if isinstance(data, dict) and data.get("type") == "step-finish" and isinstance(data.get("tokens"), dict):
        return data["tokens"]
    return None


def step_model(data):
    """The (provider, model) a step-finish part names for itself, or
    (None, None).

    A part that names one is naming the model the call was actually served
    by, which is finer than the message's: Kilo records its router's choice
    here while the message holds the alias the user picked, so a message
    reading `kilo-auto/free` covers a call billed as another vendor's model.
    OpenCode's own recordings carry no model on a part at all, so this only
    ever refines a name and never replaces a known one with nothing.

    Both halves or neither. Taking one from the part and the other from the
    message would name a pairing that never served anything, and a provider
    decides more than a name: it is what anthropic_like() reads, so a
    crossed pair can change the arithmetic of a record old enough for the
    provider to still be deciding it.
    """
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        return None, None
    provider, name = tokens.text(model.get("providerID")), tokens.text(model.get("modelID"))
    return (provider, name) if provider and name else (None, None)


def message_roots(data):
    """The worktree roots a message records, which place a session whose own
    directory is missing or empty."""
    path = data.get("path") if isinstance(data.get("path"), dict) else {}
    return {p for p in (tokens.text(path.get("root")), tokens.text(path.get("cwd"))) if p}


def session_slot(sessions, session_id):
    """The record kept for a session, created empty on first sight. A session
    can be described by several generations and by its own messages, so its
    fields are filled in as each store is read."""
    return sessions.setdefault(session_id, {"project": None, "directory": None,
                                            "version": (), "roots": set()})


def describe_session(sessions, session_id, project=None, directory=None, version=None):
    """Fill in what a store knows about a session, newest store last."""
    slot = session_slot(sessions, session_id)
    if project:
        slot["project"] = project
    if directory:
        slot["directory"] = directory
    if version:
        slot["version"] = version
    return slot


def json_value(value):
    """(a JSON data column as a dict, whether it was damaged). sqlite3 hands
    the column back as text or bytes. A row whose JSON will not parse is
    counted rather than passed over in silence, as the other readers count a
    line they cannot parse."""
    if isinstance(value, dict):
        return value, False
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str) and value:
        try:
            doc = json.loads(value)
        except ValueError:
            return {}, True
        return (doc, False) if isinstance(doc, dict) else ({}, True)
    return {}, False


def pick(fields, data, *names):
    """The first of `names` a row carries, in its columns or in its JSON.

    The schema has moved for eleven months of releases: a field can be a
    column in one version and only inside `data` in another, so both are
    asked, and an empty string counts as missing (a legacy session's
    directory is stored that way).
    """
    for name in names:
        for source in (fields, data):
            value = source.get(name)
            if value not in (None, ""):
                return value
    return None


def table_rows(conn, table, damaged=None):
    """Each row of a table as (columns dict, parsed data), lazily, so a large
    store is never held in memory at once. A row whose JSON column will not
    parse is counted in `damaged`, a one-element list used as a counter."""
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    for row in conn.execute(f"SELECT * FROM {table}"):
        fields = dict(zip(columns, row))
        data, bad = json_value(fields.get("data"))
        if bad and damaged is not None:
            damaged[0] += 1
        yield fields, data


def read_database(path):
    """(sessions, records, unreadable, damaged rows) from one database.

    The database is opened read-only through a URI, which reads a consistent
    snapshot while OpenCode is writing; `immutable` is not used, because it
    would ignore the write-ahead log. A file that will not open, or that
    holds no session table, counts as unreadable rather than raising.
    """
    sessions, records, damaged = {}, [], [0]
    try:
        uri = "file:" + urllib.request.pathname2url(os.path.abspath(path)) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except (sqlite3.Error, OSError, ValueError):
        return sessions, records, 1, 0
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # A fresh channel database can hold the V2 tables alone, so either
        # message table makes this a store rather than a damaged file.
        if "session" not in tables or not tables & {"message", "session_message"}:
            return sessions, records, 1, 0
        for fields, data in table_rows(conn, "session", damaged):
            session_id = tokens.text(pick(fields, data, "id"))
            if session_id:
                describe_session(sessions, session_id,
                                 project=tokens.text(pick(fields, data, "project_id", "projectID")),
                                 directory=tokens.text(pick(fields, data, "directory")),
                                 version=version_of(pick(fields, data, "version")))
        parts = {}
        if "part" in tables:
            for fields, data in table_rows(conn, "part", damaged):
                usage = step_tokens(data)
                part_id = tokens.text(pick(fields, data, "id"))
                message_id = tokens.text(pick(fields, data, "message_id", "messageID"))
                if usage is not None and part_id and message_id:
                    parts.setdefault(message_id, []).append((part_id, usage, step_model(data)))
        for fields, data in (table_rows(conn, "message", damaged) if "message" in tables else ()):
            message_id = tokens.text(pick(fields, data, "id"))
            session_id = tokens.text(pick(fields, data, "session_id", "sessionID"))
            if not message_id or not session_id:
                continue
            slot = session_slot(sessions, session_id)
            slot["roots"] |= message_roots(data)
            records += message_records(session_id, message_id, data, parts.get(message_id, []))
        if "session_message" in tables:
            records += read_v2_messages(conn, sessions, damaged)
    except READ_ERRORS:
        return sessions, records, 1, damaged[0]
    finally:
        conn.close()
    return sessions, records, 0, damaged[0]


def read_v2_messages(conn, sessions, damaged=None):
    """The assistant rows of the experimental session_message table.

    These are a projection of the V1 rows and carry different ids, so
    nothing merges them: scan() keeps them only for a session whose V1
    tables hold no usage, which is what a session written by the V2 runner
    alone looks like. The table exists from v1.14.34, so a row in it is
    never read under an older release's counter rule, whatever version its
    session row names. A fork's copies are skipped here as they are in the
    V1 tables, or a forked V2 session would count every call twice.
    """
    records = []
    for fields, data in table_rows(conn, "session_message", damaged):
        session_id = tokens.text(pick(fields, data, "session_id", "sessionID"))
        row_id = tokens.text(pick(fields, data, "id"))
        kind = tokens.text(pick(fields, data, "type")) or tokens.text(data.get("role"))
        if not session_id or not row_id or kind != "assistant":
            continue
        slot = session_slot(sessions, session_id)
        slot["roots"] |= message_roots(data)
        usage = data.get("tokens")
        t = data.get("time") if isinstance(data.get("time"), dict) else {}
        created = tokens.count(t.get("created"))
        if isinstance(usage, dict) and not fork_copy(row_id, created):
            records.append(Record(key=row_id, session=session_id, message_id=row_id,
                                  time_ms=created, provider=tokens.text(data.get("providerID")),
                                  model=tokens.text(data.get("modelID")), tokens=usage,
                                  version=max(slot["version"], V2_TABLE_FROM), v2=True))
    return records


def load_json(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        doc = json.load(f)
    return doc if isinstance(doc, dict) else {}


def read_file_store(sessions_glob, messages_glob, parts_glob, project_from_path=None):
    """(sessions, records, unreadable) from one of the file stores.

    The two file layouts differ only in where each kind of file sits, so both
    are read by the same walk. A part file is parsed only when its text names
    a step-finish, as the other readers prefilter, because a store holds one
    part file per tool call and per line of output.
    """
    sessions, records, unreadable = {}, [], 0
    for path in sorted(glob.glob(sessions_glob)):
        try:
            doc = load_json(path)
        except READ_ERRORS:
            unreadable += 1
            continue
        session_id = tokens.text(doc.get("id")) or os.path.splitext(os.path.basename(path))[0]
        project = tokens.text(doc.get("projectID"))
        if not project and project_from_path:
            project = project_from_path(path)
        describe_session(sessions, session_id, project=project,
                         directory=tokens.text(doc.get("directory")),
                         version=version_of(doc.get("version")))
    parts = {}
    for path in sorted(glob.glob(parts_glob)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if "step-finish" not in text:
                continue
            doc = json.loads(text)
        except READ_ERRORS:
            unreadable += 1
            continue
        if not isinstance(doc, dict):
            unreadable += 1
            continue
        usage = step_tokens(doc)
        part_id = tokens.text(doc.get("id")) or os.path.splitext(os.path.basename(path))[0]
        message_id = tokens.text(doc.get("messageID")) or os.path.basename(os.path.dirname(path))
        if usage is not None and message_id:
            parts.setdefault(message_id, []).append((part_id, usage, step_model(doc)))
    for path in sorted(glob.glob(messages_glob)):
        try:
            doc = load_json(path)
        except READ_ERRORS:
            unreadable += 1
            continue
        message_id = tokens.text(doc.get("id")) or os.path.splitext(os.path.basename(path))[0]
        session_id = tokens.text(doc.get("sessionID")) or os.path.basename(os.path.dirname(path))
        slot = session_slot(sessions, session_id)
        slot["roots"] |= message_roots(doc)
        records += message_records(session_id, message_id, doc, parts.get(message_id, []))
    return sessions, records, unreadable


def read_j1(home):
    """The v0.6.0 to v1.1.65 store: storage/{session,message,part}/...

    A file that will not parse is counted as unreadable rather than as a
    damaged row: in a file store the file is the record.
    """
    root = os.path.join(home, "storage")
    return read_file_store(os.path.join(root, "session", "*", "*.json"),
                           os.path.join(root, "message", "*", "*.json"),
                           os.path.join(root, "part", "*", "*.json"),
                           project_from_path=lambda p: os.path.basename(os.path.dirname(p)))


def read_j0(home):
    """The v0.1.0 to v0.5.29 stores, one per project directory.

    The directory's name is the worktree with its separators replaced, which
    cannot be turned back into a path, so such a session is placed by the
    worktree roots its messages record. A v0.1.x message kept its usage under
    `metadata.assistant` and is not read: guessing at it would be worse than
    the run saying it read nothing.
    """
    sessions, records, unreadable = {}, [], 0
    for root in sorted(glob.glob(os.path.join(home, "project", "*", "storage"))):
        found, rows, bad = read_file_store(
            os.path.join(root, "session", "info", "*.json"),
            os.path.join(root, "session", "message", "*", "*.json"),
            os.path.join(root, "session", "part", "*", "*", "*.json"))
        for session_id, slot in found.items():
            target = session_slot(sessions, session_id)
            target.update({k: v for k, v in slot.items() if k != "roots" and v})
            target["roots"] |= slot["roots"]
        records += rows
        unreadable += bad
    return sessions, records, unreadable


def cached_project_id(repo, store=OPENCODE):
    """The project id the tool cached in the repository's git directory, or
    None. It is written there when origin gives no id, and it survives a
    remote being renamed, which the hash does not. Each fork caches under
    its own name in the same directory, so reading the wrong one would claim
    the other tool's project."""
    result = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=paths.git_env())
    if result.returncode != 0:
        return None
    common = result.stdout.strip()
    if not common:
        return None
    path = os.path.join(repo, common) if not os.path.isabs(common) else common
    try:
        with open(os.path.join(path, store.cache_name), encoding="utf-8", errors="replace") as f:
            return tokens.text(f.read().strip())
    except OSError:
        return None


def known_ids(repo, store=OPENCODE):
    """Every project id the tool could have given this repository: the hash of
    its remote, and the id cached in its git directory. Kilo hashes the
    remote exactly as OpenCode does, so only the cached name differs."""
    ids = set()
    key = paths.remote_key(repo)
    if key:
        ids.add(hashlib.sha1(("git-remote:" + key).encode("utf-8")).hexdigest())
    cached = cached_project_id(repo, store)
    if cached:
        ids.add(cached)
    return ids


def inside_repo(directory, repo_real):
    """Whether a directory is the repository's or below it, as real paths."""
    if not directory:
        return False
    real = os.path.realpath(directory)
    return real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep)


def belongs(session, repo_real, ids, known_commit):
    """Whether a session's work was on this repository.

    Its project id decides when the repository's own id is known, which takes
    in every clone, worktree and sub-agent session. Otherwise the directory
    decides, but only when the project id names no other repository: a
    40-digit id that is not this repository's root commit belongs to another
    remote, or to another history cloned to the same path, exactly as Codex's
    rule reads it.
    """
    project = tokens.text(session["project"])
    if project and project in ids:
        return True
    directories = session["roots"] | ({session["directory"]} if session["directory"] else set())
    if not any(inside_repo(d, repo_real) for d in directories):
        return False
    if not project or project == "global":
        return True
    return known_commit(project)


def model_key(record):
    """How a call is named in the archive: the provider and the model, so a
    model billed through two providers keeps them apart. A model id can hold a
    slash of its own (openrouter/anthropic/claude-sonnet-4.5); price_id reads
    the last part either way."""
    if record.provider and record.model:
        return f"{record.provider}/{record.model}"
    return record.model


def read_home(home, store=OPENCODE):
    """(sessions, records, unreadable, damaged rows) from one home: a data
    directory with any of the four stores in it, or a database file.

    The stores are read oldest first, so that where two hold the same record,
    the newest copy is the one kept -- a record the migrations copied into
    the database keeps its id, so `scan` counts it once. A fork reads the
    database names its own releases wrote, in the order its descriptor
    lists them.
    """
    sessions, records, unreadable, damaged = {}, [], 0, 0

    def take(found, rows, bad, rows_damaged=0):
        nonlocal unreadable, damaged
        for session_id, slot in found.items():
            target = session_slot(sessions, session_id)
            target.update({k: v for k, v in slot.items() if k != "roots" and v})
            target["roots"] |= slot["roots"]
        records.extend(rows)
        unreadable += bad
        damaged += rows_damaged

    if os.path.isfile(home):
        take(*read_database(home))
        return sessions, records, unreadable, damaged
    if not os.path.isdir(home):
        return sessions, records, unreadable, damaged
    if store.file_stores:
        take(*read_j0(home))
        take(*read_j1(home))
    # Pattern by pattern, so that `databases` decides which name is read
    # last and therefore which copy of a shared record is kept; sorted
    # within a pattern, so that a channel order is at least stable. Each
    # path once, because two patterns can overlap.
    read = set()
    for pattern in store.databases:
        for path in sorted(glob.glob(os.path.join(home, pattern))):
            if path not in read:
                read.add(path)
                take(*read_database(path))
    return sessions, records, unreadable, damaged


def scan(repo, homes, store=OPENCODE):
    """The repository's usage from one OpenCode-shaped store, or None when no
    session belongs to it and nothing was unreadable."""
    repo_real = os.path.realpath(repo)
    ids, known_commit = known_ids(repo, store), commit_lookup(repo)
    sessions, records, skipped, malformed = {}, {}, 0, 0
    for home in homes:
        found, rows, bad, bad_rows = read_home(home, store)
        skipped += bad
        malformed += bad_rows
        for session_id, slot in found.items():
            target = session_slot(sessions, session_id)
            target.update({k: v for k, v in slot.items() if k != "roots" and v})
            target["roots"] |= slot["roots"]
        for record in rows:
            # A record the migrations copied keeps its id, so the newest
            # store read wins and the call is counted once.
            records[record.key] = record
    mine = {session_id for session_id, slot in sessions.items()
            if belongs(slot, repo_real, ids, known_commit)}
    # A store that holds nothing of ours is no logs at all - but a row that
    # would not parse is worth saying, or the silence this counter exists to
    # end comes back whenever the damage is all there was.
    if not mine and not skipped and not malformed:
        return None
    counted = []
    for record in records.values():
        if record.session not in mine:
            continue
        date = tokens.day_ms(record.time_ms)
        # A fork's own version numbering means nothing to these eras, so a
        # floor stands in for it. The floor does not claim to name the rule
        # that applied; it keeps a record off era A, the only subtracting
        # rule a version-less record can reach, at the cost of leaving a
        # genuine era-A record's cache read in `input` as well as in
        # `cache_read`. A record's own `total` is still consulted first,
        # because that is evidence and this is only a default.
        version = max(record.version or sessions[record.session]["version"], store.floor)
        c = counters(record.tokens, record.provider, record.model, version)
        if date and any(c.values()):
            counted.append((record, date, c))
    # The V2 table projects the V1 rows under different ids, so a session
    # described by both would be counted twice. Only a V1 record that
    # carries usage may stand in for the V2 rows: the v1.17.9 recordings
    # hold assistant messages whose every count is zero, and dropping a
    # session's V2 usage because of one of those would lose the session
    # altogether. The decision waits until every store has been read,
    # because the two tables can sit in different channel databases.
    v1_sessions = {r.session for r, _date, _c in counted if not r.v2}
    # A message read from one generation with its step-finish parts and from
    # another without them yields two records, under a part id and under the
    # message's own. The parts are the finer reading, so the message-level
    # fallback gives way to them.
    by_part = {r.message_id for r, _date, _c in counted if r.key != r.message_id}
    days = {}
    for record, date, c in counted:
        if record.v2 and record.session in v1_sessions:
            continue
        if not record.v2 and record.key == record.message_id and record.message_id in by_part:
            continue
        tokens.record(days, date, model_key(record), c)
    return tokens.ScanResult(days, malformed, skipped)
