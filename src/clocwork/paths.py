"""Where things are: the repository, the workspace, the cache, and identity.

Two path encodings live here and must not be merged. claude_project_dir()
mirrors Claude Code's own directory naming so transcripts can be found; it
tracks an external tool and may have to change when that tool changes.
cache_key() is clocwork's own, so an upstream change to Claude Code's scheme
cannot silently relocate every cache directory and trigger hour-long
re-analyses across every repository.
"""

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone

IDENTITY_FILE = "clocwork.json"

_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
_REMOTE = re.compile(
    r"^(?:git@(?P<h1>[^:]+):|https?://(?:[^@/]+@)?(?P<h2>[^/]+)/|ssh://git@(?P<h3>[^/]+)/)"
    r"(?P<path>[^/]+/[^/]+?)(?:\.git)?/?$")


class NotARepository(RuntimeError):
    pass


class WorkspaceMismatch(RuntimeError):
    pass


def _git(cwd, *args):
    result = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
    return result.returncode, result.stdout.strip()


def find_repo(start):
    """The top-level directory of the repository containing `start`."""
    start = os.path.abspath(start)
    if not os.path.isdir(start):
        raise NotARepository(f"{start} is not a directory")
    code, top = _git(start, "rev-parse", "--show-toplevel")
    if code != 0 or not top:
        raise NotARepository(f"no git repository found at or above {start}")
    return os.path.realpath(top)


def default_workspace(repo):
    """A sibling of the repository, never inside it: ~/code/foo -> ~/code/foo-stats."""
    repo = os.path.abspath(repo).rstrip(os.sep)
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-stats")


def claude_project_dir(repo):
    """Claude Code's directory name for a repository: the absolute path with
    every non-alphanumeric character replaced by a hyphen, one for one."""
    return re.sub(r"[^a-zA-Z0-9]", "-", os.path.abspath(repo))


def cache_key(repo):
    """<basename>-<sha256(abspath)[:12]>: readable, and unique across same-named repositories."""
    path = os.path.abspath(repo).rstrip(os.sep)
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    return f"{os.path.basename(path)}-{digest}"


def cache_root(override=None, env=os.environ):
    if override:
        return override
    xdg = env.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "clocwork")
    return os.path.expanduser("~/.cache/clocwork")


def cache_path(repo, override=None, env=os.environ):
    return os.path.join(cache_root(override, env), cache_key(repo), "cloc_cache.json")


def remote_url(repo):
    """The https URL of origin when it is on a known host, else None.

    Commit links are omitted rather than broken when the host is unknown.
    """
    code, remote = _git(repo, "remote", "get-url", "origin")
    if code != 0 or not remote:
        return None
    m = _REMOTE.match(remote)
    if not m:
        return None
    host = m.group("h1") or m.group("h2") or m.group("h3")
    if host not in _HOSTS:
        return None
    return f"https://{host}/{m.group('path')}"


def identity(repo, version):
    repo = os.path.realpath(repo)
    return {
        "version": version,
        "repo_remote": remote_url(repo),
        "repo_path": repo,
        "repo_name": os.path.basename(repo),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def read_identity(workspace):
    path = os.path.join(workspace, IDENTITY_FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _same(existing, current):
    if existing.get("repo_remote") and current["repo_remote"]:
        return existing["repo_remote"] == current["repo_remote"]
    return existing.get("repo_path") == current["repo_path"]


def check_identity(workspace, repo, version):
    """Refuse to run a workspace against a repository other than its own.

    The workspace holds token_usage.json, the one file that cannot be
    regenerated, so no ordinary mistake may overwrite it with another
    repository's data. The remote URL is compared first, the absolute path
    only when there is no remote.
    """
    current = identity(repo, version)
    existing = read_identity(workspace)
    if existing is None:
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, IDENTITY_FILE), "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
            f.write("\n")
        return current
    if not _same(existing, current):
        theirs = existing.get("repo_remote") or existing.get("repo_path")
        ours = current["repo_remote"] or current["repo_path"]
        raise WorkspaceMismatch(
            f"{workspace} holds data for {theirs}, not {ours}. "
            f"Pass -o DIR to use a different workspace.")
    return existing
