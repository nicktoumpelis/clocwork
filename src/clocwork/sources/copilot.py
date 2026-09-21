"""GitHub Copilot CLI: one events.jsonl per session under
$COPILOT_HOME/session-state/<session id>/, a JSON record per line with a
type, an ISO 8601 timestamp and a data object; and, from about 1.0.83,
$COPILOT_HOME/session-store.db, whose assistant_usage_events table holds a
row per model call.

In the log, only session.shutdown carries token counts, in modelMetrics, and they are
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

In the log, usage exists only at shutdown, so a session read from its
snapshots lands on the UTC day of the snapshot that carried them. The store's
rows are per call and carry their own created_at, and on 1.0.87 they sum
exactly to the same session's last snapshot. scan() reads each session from
one of the two, never both: the one holding more tokens, and the rows on a
tie. A row's input_tokens contains both cache buckets, as inputTokens does,
and its token_details_json names the uncached remainder, so a row is read
and checked exactly as a snapshot row is.
"""

import json
import os
import re
import sqlite3
import urllib.request

from clocwork import paths, tokens
from clocwork.sources.codex import commit_lookup

KEY = "copilot"
LABEL = "Copilot CLI"
# The name agents.VENDORS gives a trailer that credits Copilot. Copilot CLI
# asks its model to end commit messages with `Co-authored-by: Copilot
# <223556219+Copilot@users.noreply.github.com>` while includeCoAuthoredBy is
# on, which it is by default -- an instruction in the system prompt, so a
# commit can still lack it (checked on 1.0.87). A trailer naming GitHub's
# cloud Copilot agent resolves to the same name, so the two are not told
# apart.
AGENT = re.compile(r"^Copilot\b")
SKIPPED = "damaged, or not readable as text"
# Counted: a line that is not JSON, a snapshot whose own uncached input
# contradicts the one derived from it, a snapshot grown in one counter and
# fallen in another, and a snapshot with no day to archive under.
MALFORMED_UNIT = "records"

# A file that cannot be read at all is counted as unreadable rather than
# stopping the run; a record of the wrong shape is read as missing instead.
READ_ERRORS = (OSError, UnicodeError)
# Only these lines matter; messages, tool calls and checkpoints are skipped
# before they are parsed.
WANTED = ('"session.start"', '"session.resume"', '"session.shutdown"')
# The SQLite store beside session-state/, and its table of one row per model
# call. A store that will not open or query is counted as unreadable.
STORE = "session-store.db"
USAGE = "assistant_usage_events"
STORE_ERRORS = (OSError, ValueError, TypeError, sqlite3.Error)


def default_homes(env):
    home = env.get("COPILOT_HOME") or os.path.expanduser("~/.copilot")
    return [os.path.join(home, "session-state")]


# What a snapshot turns out to be, when it is not an increase.
STALE = "stale"             # already covered by a larger snapshot
BROKEN = "broken"           # counters that contradict being cumulative


def logs(homes):
    """Every session log under the homes, in path order and each once: homes
    can overlap, and reading one log twice would report the second reading's
    snapshots as contradicting the first's."""
    found = set()
    for home in homes:
        for directory, _dirs, files in os.walk(home):
            found |= {os.path.join(directory, name) for name in files if name == "events.jsonl"}
    return sorted(found)


def usage_of(metric):
    """A row's usage, or an empty one when it holds nothing of the shape
    Copilot writes."""
    usage = metric.get("usage")
    return usage if isinstance(usage, dict) else {}


def counters(metric):
    """The four counters from one model's row of a shutdown's modelMetrics.

    reasoningTokens is reported beside outputTokens and is not added to it:
    both providers' APIs count reasoning within their output figure, and
    every recorded row has tokenDetails.output equal to outputTokens with no
    reasoning bucket of its own. No record carries a total that could settle
    it the way OpenCode's does.
    """
    usage = usage_of(metric)
    return tokens.inclusive(usage.get("inputTokens"), usage.get("outputTokens"),
                            usage.get("cacheReadTokens"), usage.get("cacheWriteTokens"))


def requests(metric):
    """How many model calls a row's counts cover, cumulative like the counts,
    or None when the row reports none -- which is not the same as reporting
    none made. It is the source's only measure of turns: one snapshot stands
    for every response the session made."""
    count = metric.get("requests")
    value = count.get("count") if isinstance(count, dict) else None
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else None


def uncached(metric):
    """The uncached input a row reports for itself, or None when it reports
    none: the cross-check on reading inputTokens as inclusive."""
    details = metric.get("tokenDetails")
    field = details.get("input") if isinstance(details, dict) else None
    value = field.get("tokenCount") if isinstance(field, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def agrees(metric):
    """Whether a row's own uncached input matches the one its counters are
    read from: inputTokens less both cache buckets.

    The difference is taken here rather than read back out of counters(),
    which clamps it at zero -- so a row whose inputTokens has stopped
    containing the cache buckets is caught whichever way it has gone, and
    not only when the clamped reading happens to differ. A row that reports
    no figure of its own cannot be checked and is taken as it stands.
    """
    own = uncached(metric)
    if own is None:
        return True
    usage = usage_of(metric)
    return own == (tokens.count(usage.get("inputTokens")) - tokens.count(usage.get("cacheReadTokens"))
                   - tokens.count(usage.get("cacheWriteTokens")))


def increase(seen, now):
    """What a cumulative snapshot adds to the largest one seen before it for
    the same session and model: the field-wise difference, as
    (counters, calls), where calls is None when the row reports no request
    count.

    STALE when no counter has grown, which is a snapshot already covered by
    a larger one: a log repeating a block, or one file holding a session
    another file holds too. It adds nothing, and saying so is not the same
    as saying the log is damaged. A snapshot that has fallen somewhere and
    grown nowhere is read the same way, because nothing tells it apart from
    a replay -- so counters that had genuinely restarted mid-session, which
    no recording shows and a resume is known not to do, would be
    under-counted rather than counted.

    BROKEN when some counters have grown and others fallen, which
    contradicts the counts being cumulative. That is what this whole reading
    rests on, so it is the shape worth counting.

    The request count never decides either way. It measures turns, not
    tokens, and a row whose counters and own uncached input agree carries
    usage that cannot be recovered once the log expires, while a turn count
    can be understated without losing anything.
    """
    before, before_calls = seen if seen else (tokens.empty_counts(), None)
    counts, calls = now
    if all(counts[k] <= before[k] for k in tokens.COUNTERS):
        return STALE
    if any(counts[k] < before[k] for k in tokens.COUNTERS):
        return BROKEN
    added = None if calls is None else max(0, calls - (before_calls or 0))
    return {k: counts[k] - before[k] for k in tokens.COUNTERS}, added


def largest(seen, now):
    """The largest snapshot seen, once `now` has been counted as an
    increase: its counters, and its request count when it reported one, so a
    row reporting none does not lose the count a row before it gave."""
    counts, calls = now
    return counts, calls if calls is not None else (seen[1] if seen else None)


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
    once. Where no id is recorded the directory stands in for it, because
    Copilot names a session's directory after its id: a log truncated above
    its session.start still lands on the session it belongs to, rather than
    becoming a second session whose whole cumulative total is archived on
    top of the first. An ordinal keeps a second unnamed session in one log
    apart from the first -- though a named start and an unnamed one in the
    same log do fall together, since the directory is all the unnamed one
    has to go on. That under-counts rather than over-counts, in a log no
    recording has.

    A log that begins part-way through a session, with a resume, cannot tell
    that session resuming again from a second one, and reads them as one,
    which is the reading that cannot inflate a total.
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
                    key = os.path.basename(os.path.dirname(path))
                    key, unnamed = (f"{key}#{unnamed}" if unnamed else key), unnamed + 1
                current = sessions.setdefault(key, {"context": {}, "snapshots": []})
            context = data.get("context")
            if isinstance(context, dict):
                current["context"] = context
        elif kind == "session.shutdown" and current is not None:
            metrics = data.get("modelMetrics")
            if not isinstance(metrics, dict):
                continue            # not the table Copilot writes
            # A session that called no model shuts down with this table
            # present and empty, as one of the recordings does, and so adds
            # no snapshot.
            date = tokens.day(rec.get("timestamp"))
            current["snapshots"] += [(date, model, metric) for model, metric in metrics.items()
                                     if isinstance(metric, dict)]
    return malformed


def archive_session(days, snapshots):
    """Record what each of one session's snapshots adds to the ones before
    it; the snapshots that could not be read."""
    seen, malformed = {}, 0
    for date, model, metric in snapshots:
        if not agrees(metric):
            malformed += 1
            continue            # inputTokens no longer contains the cache buckets
        if not date:
            # No day to archive under. Left out of `seen` too, so the next
            # snapshot's increase still covers whatever this one held --
            # advancing it here would drop those tokens for good.
            malformed += 1
            continue
        now = (counters(metric), requests(metric))
        added = increase(seen.get(model), now)
        if added is BROKEN:
            malformed += 1
            continue
        if added is STALE:
            continue
        counts, calls = added
        seen[model] = largest(seen.get(model), now)
        # A row reporting no request count still stands for at least the one
        # response its tokens came from; one that reports a count is taken
        # at its word, even where that count has not moved. An increase is
        # never all zeros, since STALE covers exactly that case.
        tokens.record(days, date, model, counts, 1 if calls is None else calls)
    return malformed


def stores(homes):
    """Every session-store.db the homes reach, each once. A home is the
    session-state directory, so its store sits beside it; one given as the
    Copilot directory itself holds it directly."""
    found = {}
    for home in homes:
        home = os.path.normpath(home)
        for path in (os.path.join(os.path.dirname(home), STORE), os.path.join(home, STORE)):
            if os.path.isfile(path):
                found.setdefault(os.path.realpath(path), path)
    return sorted(found.values())


def row_metric(input_tokens, output_tokens, cache_read, cache_write, details):
    """A store row in the shape of a shutdown's modelMetrics row, so the two
    are read by the same counters() and checked by the same agrees(). The
    row's token_details_json lists its buckets by tokenType; the input one
    is its own uncached figure, as tokenDetails.input is a snapshot's."""
    metric = {"usage": {"inputTokens": input_tokens, "outputTokens": output_tokens,
                        "cacheReadTokens": cache_read, "cacheWriteTokens": cache_write}}
    try:
        buckets = json.loads(details) if isinstance(details, str) else None
    except ValueError:
        buckets = None
    for bucket in buckets if isinstance(buckets, list) else ():
        if isinstance(bucket, dict) and bucket.get("tokenType") == "input":
            metric["tokenDetails"] = {"input": {"tokenCount": bucket.get("tokenCount")}}
    return metric


def read_store(path):
    """(calls, directories, unreadable) from one session-store.db: each
    session's calls as {row id: (date, model, metric)}, and the working
    directory the store records for each session. Keyed by the row's id, so a
    copy of the store read beside the original adds no call twice.

    A store from before the usage table holds no calls, which is not damage.
    One that will not open or query at all is unreadable, and nothing in it
    is used.
    """
    calls, directories = {}, {}
    try:
        uri = "file:" + urllib.request.pathname2url(os.path.abspath(path)) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    except STORE_ERRORS:
        return {}, {}, 1
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "sessions" in tables:
            for session, cwd in conn.execute("SELECT id, cwd FROM sessions"):
                if tokens.text(session) and tokens.text(cwd):
                    directories[session] = cwd
        if USAGE in tables:
            for row, session, model, *usage, details, created in conn.execute(
                    "SELECT id, session_id, model, input_tokens, output_tokens, cache_read_tokens,"
                    " cache_write_tokens, token_details_json, created_at"
                    f" FROM {USAGE} ORDER BY id"):
                if tokens.text(session):
                    calls.setdefault(session, {})[row] = (tokens.day(created), model,
                                                          row_metric(*usage, details))
    except STORE_ERRORS:
        return {}, {}, 1
    finally:
        conn.close()
    return calls, directories, 0


def archive_calls(days, calls):
    """Record one session's per-call rows, each its own turn on its own
    day; the rows that could not be read."""
    malformed = 0
    for date, model, metric in calls:
        if not agrees(metric) or not date:
            malformed += 1
            continue
        tokens.record(days, date, model, counters(metric))
    return malformed


def everything(days):
    """Every token a scan's days hold, across days, models and counters."""
    return sum(tokens.source_total(day) for day in days.values())


def add_days(days, more):
    """Add one session's days to the scan's."""
    for date, day in more.items():
        for model, counts in day["models"].items():
            tokens.record(days, date, model, counts, turns=0)
        days.setdefault(date, {"turns": 0, "models": {}})["turns"] += day["turns"]


def scan(repo, homes):
    """The repository's Copilot CLI usage, or None when no session in the
    homes belongs to it and none was unreadable.

    A session can be read two ways: from its shutdown snapshots, and from the
    store's per-call rows. It is counted from one of them, never both, and
    from the one that holds more tokens -- the rows on a tie, because they
    date each call. The snapshots hold more when the session began before
    the table existed and the rows cover only its later calls; the rows hold
    more when the session ended without a shutdown. A session whose log is
    gone is placed by the directory the store records for it. A malformed
    snapshot or row is counted whichever source the session is read from:
    it is damage in the logs either way.

    A log whose starts name no session keys them by its directory, the
    second and later with an ordinal (`dir#1`); the store keys the same
    calls by the directory alone. So the rows are weighed against every
    part of the log at once -- against the first alone they would win, and
    the later parts be counted again beside them.

    The archive keeps the larger record per day, so a session's tokens must
    not move between days from one run to the next. Here they move when the
    store cannot give the rows its logs cover -- rows pruned, or the whole
    store unreadable for one run, say locked while Copilot writes it: the
    session falls back to its snapshots and lands on its shutdown days,
    beside the per-call days already archived. The unreadable store is
    counted as skipped. Whether Copilot prunes the store is not known.
    """
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
    stored, directories = {}, {}
    for path in stores(homes):
        calls, where, unreadable = read_store(path)
        skipped += unreadable
        for session, rows in calls.items():
            stored.setdefault(session, {}).update(rows)
        directories.update(where)
    parts = {}
    for key in sessions:
        parts.setdefault(key.split("#", 1)[0], []).append(key)
    for key in sorted(set(parts) | set(stored)):
        logged = [sessions[part] for part in sorted(parts.get(key, ()))]
        if key not in stored:
            # No rows: each part of the log stands alone, as it always has.
            for session in logged:
                if belongs(session["context"], repo_real, remote, known_commit):
                    belonged = True
                    malformed += archive_session(days, session["snapshots"])
            continue
        contexts = [session["context"] for session in logged if session["context"]]
        context = contexts[0] if contexts else (
            {"cwd": directories[key]} if key in directories else {})
        if not belongs(context, repo_real, remote, known_commit):
            continue
        belonged = True
        from_logs, from_rows = {}, {}
        for session in logged:
            malformed += archive_session(from_logs, session["snapshots"])
        malformed += archive_calls(from_rows, stored[key].values())
        rows_win = everything(from_rows) >= everything(from_logs)
        add_days(days, from_rows if rows_win else from_logs)
    if not belonged and not skipped:
        return None
    return tokens.ScanResult(days, malformed, skipped)
