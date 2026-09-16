"""The agent log fixtures in tests/fixtures, installed where a reader looks.

The committed sessions name a placeholder repository: every working
directory is PLACEHOLDER, Codex's remote is REMOTE and Gemini's project hash
is the hash of PLACEHOLDER. install() copies one agent's tree into a home
directory with those replaced by a real, temporary repository.
"""

import hashlib
import json
import os

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
    with open(os.path.join(FIXTURES, agent, rel), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def install(agent, home, repo, remote=REMOTE):
    """Copy one agent's fixtures under `home`, pointed at `repo`; the paths written."""
    root = os.path.join(FIXTURES, agent)
    swaps = ((project_hash(PLACEHOLDER), project_hash(repo)),
             (json.dumps(PLACEHOLDER)[1:-1], json.dumps(repo)[1:-1]),
             (REMOTE, remote))
    written = []
    for rel in files(agent):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = f.read()
        for old, new in swaps:
            text = text.replace(old, new)
        target = os.path.join(home, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(target)
    return written
