"""The agent log fixtures in tests/fixtures, installed where a reader looks.

The committed sessions name a placeholder repository: every working
directory is PLACEHOLDER, Codex's remote is REMOTE and Gemini's project hash
is the hash of PLACEHOLDER. install() copies one agent's tree into a home
directory with those replaced by a real, temporary repository.

Antigravity keeps each conversation in a SQLite database of protobuf
blobs. Its rows are committed as JSONL, one directory per conversation, with
each blob written as its field tree ({"9": {"2": 11874}}); install() encodes
them back and builds the databases. Its CLI logs are committed as the one
fact the reader takes from them, and written back in agy's own format; its
history.jsonl is copied with the placeholders swapped, as the rest are.

OpenCode keeps its sessions in SQLite, which a repository cannot hold as a
readable, diffable fixture. Its rows are committed as JSONL instead, one
file per table under `s1/` for rows as recorded, `s1-derived/` for real
counts whose ids had to be minted, and `s1-synthetic/` for the hand-written
ones; install() builds one database from all of them. Its file-store
generations are committed as the files themselves.
"""

import hashlib
import json
import os
import sqlite3

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
PLACEHOLDER = "/work/agent-sample"
# A directory outside the placeholder repository, as a second workspace
# (Antigravity's --add-dir); install() creates it beside the test repository.
ELSEWHERE = "/work/elsewhere"
REMOTE = "https://github.com/example/agent-sample.git"


def project_hash(path):
    """Gemini CLI's name for a project: the SHA-256 of its root path."""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def files(agent):
    """Every fixture file of one agent ("codex", "copilot", "gemini" or
    "opencode"), relative to its tree."""
    root = os.path.join(FIXTURES, agent)
    return sorted(os.path.relpath(os.path.join(d, name), root)
                  for d, _dirs, names in os.walk(root) for name in names)


def records(agent, rel):
    """The JSON records in one fixture file. A file store's session, message
    and part files are each a single document; everything else is JSONL."""
    with open(os.path.join(FIXTURES, agent, rel), encoding="utf-8") as f:
        text = f.read()
    if rel.endswith(".json"):
        return [json.loads(text)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def table_rows(rel, text):
    """(table, rows) for a committed database fixture: the file's name is its
    table, so the columns are the ones the real store uses."""
    return os.path.splitext(os.path.basename(rel))[0], [json.loads(l) for l in text.splitlines() if l.strip()]


def build_database(path, tables):
    """Write the rows of each table into a SQLite database, giving every
    column the type SQLite would infer. A dict or list value is stored as the
    JSON text OpenCode stores."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for table, rows in tables.items():
            columns = list(dict.fromkeys(k for row in rows for k in row))
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(columns)})")
            for row in rows:
                values = [json.dumps(row[c], separators=(",", ":")) if isinstance(row.get(c), (dict, list))
                          else row.get(c) for c in columns]
                conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
                             f"({', '.join('?' * len(columns))})", values)
        conn.commit()
    finally:
        conn.close()


def varint(n):
    if n < 0:
        raise ValueError("a fixture blob holds no negative number")
    out = bytearray()
    while True:
        low, n = n & 0x7F, n >> 7
        out.append(low | (0x80 if n else 0))
        if not n:
            return bytes(out)


def protobuf(tree):
    """A message from its field tree: a number is a varint, a string is
    UTF-8 bytes and a dict is a nested message, each length-delimited."""
    out = bytearray()
    for field, value in tree.items():
        if not isinstance(value, (int, str, dict)):
            raise ValueError(f"field {field}: a fixture blob holds numbers, strings and messages")
        if isinstance(value, int):
            out += varint(int(field) << 3) + varint(value)
            continue
        body = protobuf(value) if isinstance(value, dict) else value.encode("utf-8")
        out += varint(int(field) << 3 | 2) + varint(len(body)) + body
    return bytes(out)


# The two lines of an agy CLI log the reader takes: the workspace a run was
# started in, and each conversation it created.
AGY_WORKSPACE = ("I0922 09:36:40.604617       1 server.go:309] Creating CLI server backend: "
                 "product=antigravity workspaceDirs=[{}] appDataDir={}\n")
AGY_CREATED = "I0922 09:36:42.773709       1 server.go:1224] Created conversation {}\n"


def install_antigravity(root, home, swap):
    """Build the conversation databases, the summaries database, the CLI
    logs and the prompt history of the Antigravity fixture under `home`; the
    paths written."""
    written = []
    conversations = os.path.join(root, "conversations")
    for cid in sorted(os.listdir(conversations)):
        tables = {}
        for name in sorted(os.listdir(os.path.join(conversations, cid))):
            with open(os.path.join(conversations, cid, name), encoding="utf-8") as f:
                rows = [json.loads(l) for l in f.read().splitlines() if l.strip()]
            tables[os.path.splitext(name)[0]] = [{k: protobuf(v) if isinstance(v, dict) else v
                                                 for k, v in row.items()} for row in rows]
        path = os.path.join(home, "conversations", cid + ".db")
        build_database(path, tables)
        written.append(path)
    with open(os.path.join(root, "conversation_summaries.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(swap(l)) for l in f.read().splitlines() if l.strip()]
    path = os.path.join(home, "conversation_summaries.db")
    build_database(path, {"conversation_summaries": rows})
    written.append(path)
    with open(os.path.join(root, "log", "runs.jsonl"), encoding="utf-8") as f:
        runs = [json.loads(swap(l)) for l in f.read().splitlines() if l.strip()]
    with open(os.path.join(root, "history.jsonl"), encoding="utf-8") as f:
        history = swap(f.read())
    path = os.path.join(home, "history.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(history)
    written.append(path)
    for run in runs:
        path = os.path.join(home, "log", run["log"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(AGY_WORKSPACE.format(" ".join(run["workspaceDirs"]), home))
            f.writelines(AGY_CREATED.format(cid) for cid in run["created"])
        written.append(path)
    return written


def install(agent, home, repo, remote=REMOTE, database="opencode.db"):
    """Copy one agent's fixtures under `home`, pointed at `repo`; the paths written.

    A file under an `s1*` directory is a table of OpenCode's database rather
    than a file the agent wrote, so those rows are collected and built into
    one database instead of being copied.
    """
    root = os.path.join(FIXTURES, agent)
    swaps = ((project_hash(PLACEHOLDER), project_hash(repo)),
             (json.dumps(ELSEWHERE)[1:-1], json.dumps(os.path.join(os.path.dirname(repo), "elsewhere"))[1:-1]),
             (json.dumps(PLACEHOLDER)[1:-1], json.dumps(repo)[1:-1]),
             (REMOTE, remote))
    if agent == "antigravity":
        os.makedirs(os.path.join(os.path.dirname(repo), "elsewhere"), exist_ok=True)

        def swap(text):
            for old, new in swaps:
                text = text.replace(old, new)
            return text
        return install_antigravity(root, home, swap)
    written, tables = [], {}
    for rel in files(agent):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = f.read()
        for old, new in swaps:
            text = text.replace(old, new)
        if rel.split(os.sep)[0].startswith("s1"):
            table, rows = table_rows(rel, text)
            tables.setdefault(table, []).extend(rows)
            continue
        target = os.path.join(home, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(target)
    if tables:
        path = os.path.join(home, database)
        build_database(path, tables)
        written.append(path)
    return written
