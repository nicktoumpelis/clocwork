"""Which commit each line at a revision last came from: one `git blame` per
file, in parallel, cached by the file's blob and path.

The result is the page's "share of code at HEAD from AI-assisted commits":
every line of every file cloc counted at the revision, credited to the
commit that last touched it, and through the analysis's attribution to that
commit's agent. Blame credits the last commit to touch a line, so a human
reformat takes an agent's lines and vice versa; the page says so.

A file's blame changes only when the file does or its history is rewritten,
so the cache is keyed by blob id and path and survives a re-run after a few
commits with only the changed files blamed again.
"""

import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from clocwork import paths

# A porcelain header: the commit, the line's number in it and at the
# revision, and on a group's first line how many lines the group has.
HEADER = re.compile(r"^([0-9a-f]{40}) \d+ \d+(?: \d+)?$")


class BlameError(RuntimeError):
    pass


def tree(repo, rev):
    """{path: blob id} of rev's regular files."""
    result = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", "--full-tree", rev],
                            capture_output=True, text=True, env=paths.git_env())
    if result.returncode != 0:
        raise BlameError(f"git ls-tree {rev} failed: {result.stderr.strip()}")
    files = {}
    for entry in result.stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if path and meta.startswith("100"):
            files[path] = meta.split()[2]
    return files


def parse_porcelain(text):
    """{commit: lines} from `git blame --porcelain` output."""
    counts = {}
    for line in text.split("\n"):
        m = HEADER.match(line)
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def blame_file(repo, rev, path):
    """{commit: lines} for one file at rev."""
    result = subprocess.run(["git", "-C", repo, "blame", "--porcelain", rev, "--", path],
                            capture_output=True, text=True, errors="replace", env=paths.git_env())
    if result.returncode != 0:
        raise BlameError(f"git blame {path} failed: {result.stderr.strip()}")
    return parse_porcelain(result.stdout)


class Cache:
    """{blob id + path: {commit: lines}} in one JSON file beside the cloc cache."""

    VERSION = 1

    def __init__(self, path):
        self.path = path
        self.entries = {}
        self.dirty = 0
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                return
            if data.get("version") == self.VERSION:
                self.entries = data.get("files", {})

    @staticmethod
    def key(blob, path):
        return blob + " " + path

    def get(self, blob, path):
        return self.entries.get(self.key(blob, path))

    def put(self, blob, path, counts):
        self.entries[self.key(blob, path)] = counts
        self.dirty += 1

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": self.VERSION, "files": self.entries}, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, self.path)
        self.dirty = 0


def lines_at(repo, rev, files, cache, jobs=1, on_start=None):
    """{commit: lines} over `files` at rev, `jobs` blames at a time.

    `files` are the paths to credit, normally those cloc counted. A path not
    in rev's tree is skipped. `on_start`, if given, is told how many files
    the cache does not hold, before they are blamed, and only when there are
    any. Returns the counts and how many files were blamed afresh rather
    than read from the cache.
    """
    blobs = tree(repo, rev)
    wanted = [(path, blobs[path]) for path in sorted(files) if path in blobs]
    totals, fresh = {}, 0

    def add(counts):
        for commit, n in counts.items():
            totals[commit] = totals.get(commit, 0) + n

    missing = []
    for path, blob in wanted:
        cached = cache.get(blob, path)
        if cached is None:
            missing.append((path, blob))
        else:
            add(cached)
    if missing and on_start:
        on_start(len(missing))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for (path, blob), counts in zip(missing, pool.map(lambda pb: blame_file(repo, rev, pb[0]), missing)):
            cache.put(blob, path, counts)
            add(counts)
            fresh += 1
    if cache.dirty:
        cache.save()
    return totals, fresh


def by_agent(totals, commits):
    """The blamed lines by who wrote the commit: the summary's lines_at_head.

    `commits` are the analysis's result rows, with full_hash and agent. A
    line from a commit the history does not hold (a shallow clone's boundary,
    say) is unattributed rather than guessed at.
    """
    agent_of = {r["full_hash"]: r["agent"] for r in commits}
    human = unattributed = 0
    agents = {}
    for commit, n in totals.items():
        if commit not in agent_of:
            unattributed += n
        elif agent_of[commit]:
            agents[agent_of[commit]] = agents.get(agent_of[commit], 0) + n
        else:
            human += n
    return {"total": sum(totals.values()), "human": human, "by_agent": dict(sorted(agents.items())),
            "unattributed": unattributed}
