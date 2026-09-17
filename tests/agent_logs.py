"""The agent log fixtures in tests/fixtures, installed where a reader looks.

The committed sessions name a placeholder repository: every working
directory is PLACEHOLDER, Codex's remote is REMOTE and Gemini's project hash
is the hash of PLACEHOLDER. install() copies one agent's tree into a home
directory with those replaced by a real, temporary repository.

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
REMOTE = "https://github.com/example/agent-sample.git"


def project_hash(path):
    """Gemini CLI's name for a project: the SHA-256 of its root path."""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def files(agent):
    """Every fixture file of one agent ("codex" or "gemini"), relative to its tree."""
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


def install(agent, home, repo, remote=REMOTE, database="opencode.db"):
    """Copy one agent's fixtures under `home`, pointed at `repo`; the paths written.

    A file under an `s1*` directory is a table of OpenCode's database rather
    than a file the agent wrote, so those rows are collected and built into
    one database instead of being copied.
    """
    root = os.path.join(FIXTURES, agent)
    swaps = ((project_hash(PLACEHOLDER), project_hash(repo)),
             (json.dumps(PLACEHOLDER)[1:-1], json.dumps(repo)[1:-1]),
             (REMOTE, remote))
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
