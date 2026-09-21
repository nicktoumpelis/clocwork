"""GitHub Copilot CLI: one events.jsonl per session under
$COPILOT_HOME/session-state/<session id>/, a JSON record per line with a
type, an ISO 8601 timestamp and a data object.

Only session.shutdown carries token counts, in modelMetrics, and they are
**cumulative for the session so far** rather than per response: an
assistant.message reports its output alone, and session.usage_checkpoint
reports billing units and no tokens at all. A session that is resumed goes on
counting where it left off, and writes a further snapshot at each shutdown,
so what a snapshot adds is its increase over the largest one before it.
Reading it any other way multiplies a session's usage by the number of times
it was recorded. The public recordings in tests/fixtures/copilot hold a
session whose whole block was written twice, which the same rule absorbs.

inputTokens contains both cache buckets, so the counters are read as
inclusive(); tokenDetails reports the uncached input directly, which no other
agent's log does, and every recorded row agrees with the figure derived from
it. A row that disagrees is counted rather than archived: a format that has
moved under us should show up as a number in the log, not as quietly halved
usage.

Usage exists only at shutdown, so a session's tokens land on the UTC day of
the snapshot that carried them. This is the one source without per-message
records, and a session held open across midnight is dated by its snapshots,
which is as fine-grained as the format allows.
"""

import json
import os
import re

from clocwork import paths, tokens
from clocwork.sources.codex import commit_lookup

KEY = "copilot"
LABEL = "Copilot CLI"
# Copilot asks for "Co-authored-by: Copilot <...>" on the commits it writes.
AGENT = re.compile(r"^Copilot\b")
SKIPPED = "damaged, or not readable as text"
# Counted: a line that is not JSON, a snapshot whose own uncached input
# contradicts the one derived from it, and a snapshot whose cumulative
# counters went backwards.
MALFORMED_UNIT = "records"

# A file that cannot be read at all is counted as unreadable rather than
# stopping the run; a record of the wrong shape is read as missing instead.
READ_ERRORS = (OSError, UnicodeError)
# Only these lines matter; messages, tool calls and checkpoints are skipped
# before they are parsed.
WANTED = ('"session.start"', '"session.resume"', '"session.shutdown"')


def default_homes(env):
    home = env.get("COPILOT_HOME") or os.path.expanduser("~/.copilot")
    return [os.path.join(home, "session-state")]


def logs(homes):
    """Every session log under the homes, in path order."""
    found = []
    for home in homes:
        for directory, _dirs, files in os.walk(home):
            found += [os.path.join(directory, name) for name in files if name == "events.jsonl"]
    return sorted(found)


def counters(metric):
    """The four counters from one model's row of a shutdown's modelMetrics.

    reasoningTokens is reported beside outputTokens and is not added to it:
    both providers' APIs count reasoning within their output figure, and
    every recorded row has tokenDetails.output equal to outputTokens with no
    reasoning bucket of its own. No record carries a total that could settle
    it the way OpenCode's does.
    """
    usage = metric.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return tokens.inclusive(usage.get("inputTokens"), usage.get("outputTokens"),
                            usage.get("cacheReadTokens"), usage.get("cacheWriteTokens"))


def requests(metric):
    """How many model calls a row's counts cover, cumulative like the counts.
    It is the source's only measure of turns: one snapshot stands for every
    response the session made."""
    count = metric.get("requests")
    return max(0, tokens.count(count.get("count") if isinstance(count, dict) else None))


def uncached(metric):
    """The uncached input a row reports for itself, or None when it reports
    none: the cross-check on reading inputTokens as inclusive."""
    details = metric.get("tokenDetails")
    field = details.get("input") if isinstance(details, dict) else None
    value = field.get("tokenCount") if isinstance(field, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def increase(seen, now):
    """What a cumulative snapshot adds to the largest one seen before it for
    the same session and model: the field-wise difference, as
    (counters, requests). None when any field went backwards, which
    contradicts the counts being cumulative.
    """
    before, before_requests = seen or (tokens.empty_counts(), 0)
    counts, count = now
    if count < before_requests or any(counts[k] < before[k] for k in tokens.COUNTERS):
        return None
    return {k: counts[k] - before[k] for k in tokens.COUNTERS}, count - before_requests


def ran_inside(context, repo_real):
    """Whether a session's working directory or git root is the repository's
    or below it. Copilot records both, and in a worktree they differ; either
    one being inside is enough."""
    for key in ("cwd", "gitRoot"):
        path = tokens.text(context.get(key))
        if path:
            real = os.path.realpath(path)
            if real == repo_real or real.startswith(repo_real.rstrip(os.sep) + os.sep):
                return True
    return False


def session_remote(context):
    """host/owner/name from a session's context, in the form
    paths.remote_key builds, or None. Copilot records the two halves apart:
    the host as repositoryHost, owner/name as repository."""
    host = tokens.text(context.get("repositoryHost"))
    repository = tokens.text(context.get("repository"))
    if host and repository and "/" in repository:
        return f"{host.lower()}/{repository}"
    return None


def belongs(context, repo_real, remote, known_commit):
    """Whether a session ran on the repository.

    When both name a remote, the same remote decides, as
    paths.check_identity does, so a session from any clone counts. A session
    that recorded another remote still belongs when it ran in the
    repository's directory from one of the repository's commits: the
    repository was renamed or moved since, while a different repository
    cloned to the same path shares none of its commits. Without two remotes
    to compare, the working directory decides. This is codex.belongs' rule,
    over the fields Copilot records it in.
    """
    url = session_remote(context)
    if remote and url:
        if url.lower() == remote.lower():
            return True
        if not ran_inside(context, repo_real):
            return False
        return any(sha and known_commit(sha) for sha in
                   (tokens.text(context.get("headCommit")), tokens.text(context.get("baseCommit"))))
    return ran_inside(context, repo_real)


def read_log(lines, path, sessions):
    """Add the sessions one events.jsonl holds to `sessions`; the malformed
    records read.

    A session is {"context", "snapshots"}, where a snapshot is
    (date, model, metric) and they are kept in the order they were read.
    Only session.start names the session; session.resume carries the context
    again without an id, and session.shutdown carries neither, so the open
    session has to be followed down the file.

    Sessions are keyed by their id, across logs as well as within one, so
    blocks that share an id are read as a single sequence of snapshots.
    That is what makes a repeated block idempotent, and a session that sits
    in two places -- a copied or backed-up session-state tree -- counted
    once. A start with no id names a session of its own, keyed by where it
    is; a log that begins part-way through a session, with a resume, cannot
    tell that session resuming again from a second one, and reads them as
    one, which is the reading that cannot inflate a total.
    """
    current, unnamed, malformed = None, 0, 0
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
        kind, data = rec.get("type"), rec.get("data")
        if not isinstance(data, dict):
            continue
        if kind in ("session.start", "session.resume"):
            if kind == "session.start" or current is None:
                key = tokens.text(data.get("sessionId")) if kind == "session.start" else None
                if key is None:
                    key, unnamed = f"{path}#{unnamed}", unnamed + 1
                current = sessions.setdefault(key, {"context": {}, "snapshots": []})
            context = data.get("context")
            if isinstance(context, dict):
                current["context"] = context
        elif kind == "session.shutdown" and current is not None:
            metrics = data.get("modelMetrics")
            if not isinstance(metrics, dict):
                continue            # a session that shut down having called no model
            date = tokens.day(rec.get("timestamp"))
            current["snapshots"] += [(date, model, metric) for model, metric in metrics.items()
                                     if isinstance(metric, dict)]
    return malformed


def archive_session(days, snapshots):
    """Record what each of one session's snapshots adds; the ones that
    contradict being cumulative."""
    seen, malformed = {}, 0
    for date, model, metric in snapshots:
        counts = counters(metric)
        own = uncached(metric)
        if own is not None and own != counts["input"]:
            malformed += 1
            continue            # inputTokens no longer contains the cache buckets
        now = (counts, requests(metric))
        added = increase(seen.get(model), now)
        if added is None:
            malformed += 1
            continue
        seen[model] = now       # accepted, so this snapshot is the largest seen
        counts, turns = added
        if date and any(counts.values()):
            # A row that reports no request count still stands for at least
            # the one response its tokens came from.
            tokens.record(days, date, model, counts, max(1, turns))
    return malformed


def scan(repo, homes):
    """The repository's Copilot CLI usage, or None when no session in the
    homes belongs to it and none was unreadable."""
    repo_real = os.path.realpath(repo)
    remote = paths.remote_key(repo) if os.path.isdir(repo) else None
    known_commit = commit_lookup(repo)
    days, sessions, malformed, skipped, belonged = {}, {}, 0, 0, False
    for path in logs(homes):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                malformed += read_log(iter(f), path, sessions)
        except READ_ERRORS:
            skipped += 1
    for session in sessions.values():
        if not belongs(session["context"], repo_real, remote, known_commit):
            continue
        belonged = True
        malformed += archive_session(days, session["snapshots"])
    if not belonged and not skipped:
        return None
    return tokens.ScanResult(days, malformed, skipped)
