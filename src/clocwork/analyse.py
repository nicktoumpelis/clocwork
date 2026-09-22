#!/usr/bin/env python3
"""Analyse every commit in a repository's history: lines per language and type
via cloc, AI agent detection, and token usage from the agent log archive.

The repository, the output path, the cache, the archive and the classification
rules are all inputs; nothing here knows which repository it is measuring.
"""

import json
import re
import subprocess
import sys
from collections import namedtuple

from clocwork import classify as cf
from clocwork import cloc as cl
from clocwork import paths
from clocwork import sources as src
from clocwork import tokens as tu
from clocwork import ui
from clocwork.agents import DEFAULT_AGENTS
from clocwork.config import Config

# Merge commits carry no code of their own, so they are filed under a
# catch-all category rather than being attributed to a human or an AI agent.
MISC = "Misc"


class NoCommits(RuntimeError):
    pass


def is_merge_commit(commit):
    """Merges carry no code of their own: any multi-parent commit, plus GitHub PR merges by subject."""
    return len(commit.get("parents", [])) > 1 or commit["message"].startswith("Merge pull request")


def git(repo, *args):
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=repo, env=paths.git_env())
    return result.stdout


Rename = namedtuple("Rename", "commit old new old_blob new_blob")


def path_history(repo, rev):
    """From one walk of rev's history: every rename of a regular file as a
    Rename (the commit, both names and both blob ids), newest first, with
    git's default rename detection, and every path that was a symlink at
    any point."""
    # -z: NUL after every field and no newline between commits, so names
    # come through as written. Each commit is its hash, then per change
    # ":<modes> <ids> <status>" and its path, or two for a rename or copy.
    # Merges list no changes without -m.
    fields = git(repo, "log", "-M", "--raw", "--no-abbrev", "-z", "--format=%H", rev, "--").split("\0")
    renames, symlinks = [], set()
    commit = None
    i = 0
    while i < len(fields):
        meta = fields[i].lstrip("\n")
        if not meta.startswith(":"):
            commit = meta or commit
            i += 1
            continue
        old_mode, new_mode, old_blob, new_blob, status = meta[1:].split()[:5]
        count = 2 if status[:1] in "RC" else 1
        names = fields[i + 1:i + 1 + count]
        if "120000" in (old_mode, new_mode):
            symlinks.update(names)
        elif status.startswith("R") and len(names) == 2 and old_mode.startswith("100") and new_mode.startswith("100"):
            renames.append(Rename(commit, names[0], names[1], old_blob, new_blob))
        i += 1 + count
    return renames, symlinks


def is_shallow(repo):
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def parse_log(repo, branch, agents=DEFAULT_AGENTS):
    """Return every commit reachable from branch, oldest first, with parents, body, numstat and agent."""
    raw = git(repo, "log", branch, "--reverse",
              "--format=COMMIT_START%n%H%n%P%n%aI%n%s%n%b%nCOMMIT_BODY_END", "--numstat", "--")
    commits = []
    current = None
    in_body = False
    body_lines = []
    field_idx = 0

    def finish(c):
        c["body"] = "\n".join(body_lines)
        c["agent"] = agents.detect(c["body"])
        commits.append(c)

    for line in raw.splitlines():
        if line == "COMMIT_START":
            if current is not None:
                finish(current)
            current = {"numstat": []}
            body_lines = []
            in_body = True
            field_idx = 0
            continue
        if current is None:
            continue
        if in_body and field_idx < 4:
            value = line.strip()
            if field_idx == 0:
                current["hash"] = value
            elif field_idx == 1:
                current["parents"] = value.split() if value else []
            elif field_idx == 2:
                current["date"] = value
            elif field_idx == 3:
                current["message"] = value
            field_idx += 1
            continue
        if line == "COMMIT_BODY_END":
            in_body = False
            continue
        if in_body:
            body_lines.append(line)
            continue
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] != "-" and parts[1] != "-":
            current["numstat"].append({"additions": int(parts[0]), "deletions": int(parts[1]), "file": parts[2]})

    if current is not None:
        finish(current)
    return commits


def churn_of(result):
    """Lines added plus removed across every language and line type."""
    return sum(sum(row) for row in result["lines"].values())


def is_ai(result):
    return bool(result["agent"]) and result["agent"] != MISC


def churn_by_date(results):
    """Lines added plus removed per date, whoever wrote them.

    Merge commits carry no line matrices, so they contribute nothing here, as
    everywhere else in this project.
    """
    totals = {}
    for r in results:
        if r["date"]:
            totals[r["date"]] = totals.get(r["date"], 0) + churn_of(r)
    return totals


def source_churn_by_date(results, source):
    """Lines changed per date by the commits whose tokens `source` measures."""
    totals = {}
    if source is None:
        return totals
    for r in results:
        if r["date"] and is_ai(r) and src.source_for(r["agent"]) is source:
            totals[r["date"]] = totals.get(r["date"], 0) + churn_of(r)
    return totals


# Energy per thousand tokens, by what the model actually had to do.
#
# These four constants are the least certain numbers in this project. Published
# per-token energy figures vary by an order of magnitude between sources, and
# none of them measure an agentic coding workload with million-token contexts,
# which is what this archive contains. They are stated here, in one place, so
# that anyone who disagrees can change them and see what moves.
#
# The relative ordering is on firmer ground than the absolute values: decoding a
# token runs the whole model to produce one output, prefill processes many
# tokens in parallel and so costs far less each, and a cache read skips
# recomputation altogether and is mostly memory traffic.
WH_PER_1K_OUTPUT = 1.0
WH_PER_1K_CACHE_WRITE = 0.1
WH_PER_1K_CACHE_READ = 0.02
WH_PER_1K_INPUT = 0.1          # fresh input is prefill, same as a cache write

# Location-based grid intensity, roughly a mixed US/EU grid. Deliberately not
# the market-based figure cloud providers quote from renewable matching, which
# would put this near zero and say nothing about the electricity actually drawn.
GRID_G_CO2E_PER_KWH = 400

WH_PER_1K = {
    "output": WH_PER_1K_OUTPUT,
    "cache_write": WH_PER_1K_CACHE_WRITE,
    "cache_read": WH_PER_1K_CACHE_READ,
    "input": WH_PER_1K_INPUT,
}


def energy_estimate(counters, measured_total, lifetime_total):
    """Kilowatt-hours and kilograms of CO2e for the lifetime token ceiling.

    Only the archived window records the split between generated, prefilled and
    cached tokens, so that mix is assumed to hold across the estimated era too
    and the lifetime ceiling is divided along it. The result inherits every
    caveat the ceiling carries, and adds its own: see the constants above.
    """
    if not measured_total or not lifetime_total:
        return 0.0, 0.0
    wh = sum(WH_PER_1K[name] * (tokens / measured_total) * lifetime_total / 1000
             for name, tokens in counters.items())
    kwh = wh / 1000
    return kwh, kwh * GRID_G_CO2E_PER_KWH / 1000


# API list prices in US dollars per million tokens, from each vendor's pricing
# page on the date given. Keys are matched as prefixes, longest first, so dated
# ids ('claude-sonnet-4-5-20250929') resolve without a row each; a
# variant whose id extends another's ('gpt-5-mini', 'gemini-2.5-flash-lite')
# needs a row of its own, or it is priced as the shorter id.
#
# Anthropic: platform.claude.com/docs/en/about-claude/pricing, 2026-09-07;
# the Claude 4 generation rechecked 2026-09-17. Opus 4 and 4.1 cost three
# times what 4.5 and later do, so each Opus 4.x has a row of its own and the
# bare claude-opus-4 row, which a dated id falls back to, is the original's.
# Sonnet 4, 4.5 and 4.6 share one price, and one row.
# Cache writes are priced at the one-hour rate: Claude Code writes its cache
# with that TTL (98% of cache-write tokens in the current transcripts) and the
# archive keeps one cache-write counter. Long context carries no premium on
# these models.
#
# OpenAI: developers.openai.com/api/docs/pricing, standard tier, 2026-09-16.
# Cache writes have a price of their own from GPT-5.6 on; earlier models list
# none and report none, so their rows repeat the input price, as do the cached
# prices of the pro models, which list no caching. gpt-5.6-sol's price is
# promotional "at least through November 21, 2026": check it then.
#
# Google: ai.google.dev/gemini-api/docs/pricing, standard paid tier, text,
# 2026-09-16. The context caching price is the cached-token rate; Gemini CLI
# reports no cache writes, so that column repeats the input price.
#
# GPT-5.5 and GPT-5.4 cost more above 272K tokens of context and the Gemini
# Pro models above 200K. Those tiers are not applied: the archive holds daily
# sums, not request sizes, so every model is priced at its base tier.
PRICE_USD_PER_MTOK = {
    "claude-fable-5-1": {"input": 10.0,  "cache_write": 20.0,   "cache_read": 0.25,   "output": 50.0},
    "claude-fable-5":   {"input": 10.0,  "cache_write": 20.0,   "cache_read": 1.0,    "output": 50.0},
    "claude-opus-5":    {"input": 5.0,   "cache_write": 10.0,   "cache_read": 0.5,    "output": 25.0},
    "claude-opus-4-8":  {"input": 5.0,   "cache_write": 10.0,   "cache_read": 0.5,    "output": 25.0},
    "claude-opus-4-7":  {"input": 5.0,   "cache_write": 10.0,   "cache_read": 0.5,    "output": 25.0},
    "claude-opus-4-6":  {"input": 5.0,   "cache_write": 10.0,   "cache_read": 0.5,    "output": 25.0},
    "claude-opus-4-5":  {"input": 5.0,   "cache_write": 10.0,   "cache_read": 0.5,    "output": 25.0},
    "claude-opus-4-1":  {"input": 15.0,  "cache_write": 30.0,   "cache_read": 1.5,    "output": 75.0},
    "claude-opus-4":    {"input": 15.0,  "cache_write": 30.0,   "cache_read": 1.5,    "output": 75.0},
    "claude-sonnet-5":  {"input": 2.0,   "cache_write": 4.0,    "cache_read": 0.2,    "output": 10.0},
    "claude-sonnet-4":  {"input": 3.0,   "cache_write": 6.0,    "cache_read": 0.3,    "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0,   "cache_write": 2.0,    "cache_read": 0.1,    "output": 5.0},
    "gpt-6-astra":      {"input": 10.0,  "cache_write": 12.5,   "cache_read": 1.0,    "output": 50.0},
    "gpt-5.6-sol":      {"input": 4.0,   "cache_write": 5.0,    "cache_read": 0.4,    "output": 20.0},
    "gpt-5.6-terra":    {"input": 2.0,   "cache_write": 2.5,    "cache_read": 0.2,    "output": 12.0},
    "gpt-5.6-luna":     {"input": 0.2,   "cache_write": 0.25,   "cache_read": 0.02,   "output": 1.2},
    "gpt-5.6-cyber":    {"input": 12.5,  "cache_write": 15.625, "cache_read": 1.25,   "output": 75.0},
    "gpt-5.5":          {"input": 5.0,   "cache_write": 5.0,    "cache_read": 0.5,    "output": 30.0},
    "gpt-5.5-pro":      {"input": 30.0,  "cache_write": 30.0,   "cache_read": 30.0,   "output": 180.0},
    "gpt-5.5-cyber":    {"input": 12.5,  "cache_write": 12.5,   "cache_read": 1.25,   "output": 75.0},
    "gpt-5.4":          {"input": 2.5,   "cache_write": 2.5,    "cache_read": 0.25,   "output": 15.0},
    "gpt-5.4-mini":     {"input": 0.75,  "cache_write": 0.75,   "cache_read": 0.075,  "output": 4.5},
    "gpt-5.4-nano":     {"input": 0.2,   "cache_write": 0.2,    "cache_read": 0.02,   "output": 1.25},
    "gpt-5.4-pro":      {"input": 30.0,  "cache_write": 30.0,   "cache_read": 30.0,   "output": 180.0},
    "gpt-5.3-codex":    {"input": 1.75,  "cache_write": 1.75,   "cache_read": 0.175,  "output": 14.0},
    "gpt-5.2":          {"input": 1.75,  "cache_write": 1.75,   "cache_read": 0.175,  "output": 14.0},
    "gpt-5.2-pro":      {"input": 21.0,  "cache_write": 21.0,   "cache_read": 21.0,   "output": 168.0},
    "gpt-5.1":          {"input": 1.25,  "cache_write": 1.25,   "cache_read": 0.125,  "output": 10.0},
    "gpt-5":            {"input": 1.25,  "cache_write": 1.25,   "cache_read": 0.125,  "output": 10.0},
    "gpt-5-mini":       {"input": 0.25,  "cache_write": 0.25,   "cache_read": 0.025,  "output": 2.0},
    "gpt-5-nano":       {"input": 0.05,  "cache_write": 0.05,   "cache_read": 0.005,  "output": 0.4},
    "gpt-5-pro":        {"input": 15.0,  "cache_write": 15.0,   "cache_read": 15.0,   "output": 120.0},
    "gemini-3.8-flash":      {"input": 0.75, "cache_write": 0.75, "cache_read": 0.075, "output": 3.75},
    "gemini-3.7-flash":      {"input": 0.75, "cache_write": 0.75, "cache_read": 0.075, "output": 3.75},
    "gemini-3.6-flash":      {"input": 0.75, "cache_write": 0.75, "cache_read": 0.075, "output": 3.75},
    "gemini-3.5-flash":      {"input": 1.5,  "cache_write": 1.5,  "cache_read": 0.15,  "output": 9.0},
    "gemini-3.5-flash-lite": {"input": 0.3,  "cache_write": 0.3,  "cache_read": 0.03,  "output": 2.5},
    "gemini-3.1-pro-preview": {"input": 2.0, "cache_write": 2.0,  "cache_read": 0.2,   "output": 12.0},
    "gemini-3.1-flash-lite": {"input": 0.25, "cache_write": 0.25, "cache_read": 0.025, "output": 1.5},
    "gemini-3-flash-preview": {"input": 0.5, "cache_write": 0.5,  "cache_read": 0.05,  "output": 3.0},
    "gemini-2.5-pro":        {"input": 1.25, "cache_write": 1.25, "cache_read": 0.125, "output": 10.0},
    "gemini-2.5-flash":      {"input": 0.3,  "cache_write": 0.3,  "cache_read": 0.03,  "output": 2.5},
    "gemini-2.5-flash-lite": {"input": 0.1,  "cache_write": 0.1,  "cache_read": 0.01,  "output": 0.4},
}

# List prices already announced to change: {row key: [(first day, row), ...]},
# oldest first. Each archived day is priced at the row in force on it.
PRICE_CHANGES = {
    key: [("2027-01-01", {"input": 1.5, "cache_write": 1.5, "cache_read": 0.15, "output": 7.5})]
    for key in ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash")
}


# An id that extends a row's with one of these words names another model
# ('gpt-5.1-codex-mini' is not 'gpt-5.1'), whose price the table does not know.
VARIANT_WORDS = {"mini", "nano", "pro", "lite", "max", "codex", "spark", "cyber", "flash",
                 "image", "audio", "native", "tts", "live", "transcribe"}


# Bedrock's vendor, after an optional inference region: 'anthropic.' or
# 'us.anthropic.'. A bare id's first dot follows a digit ('gpt-5.5'), never a
# word alone.
BEDROCK_PREFIX = re.compile(r"^(?:[a-z]+(?:-[a-z]+)?\.)?[a-z]+\.(?=[a-z])")
# A colon is a router's price marker (':free', ':thinking') unless it is the
# minor part of Bedrock's version tail ('-v1:0').
BEDROCK_VERSION = re.compile(r"-v\d+:\d+$")
# Claude Code's model alias for the 1M context window, if an id ever carries it.
CONTEXT_ALIAS = re.compile(r"\[1m\]$", re.IGNORECASE)


def price_id(model):
    """The bare model id a provider's spelling names, for the price lookup
    only; the archive keeps the id as the agent wrote it.

    A path keeps its last part ('openrouter/openai/gpt-5.5', 'models/…',
    Vertex's 'publishers/google/models/…'), Bedrock's vendor and region go
    ('us.anthropic.claude-…'; its '-v1:0' suffix stays, a tail the prefix
    rule accepts), as does Vertex's '@version'. A Claude id written with a dotted
    version ('claude-opus-4.1', as OpenRouter does) takes the hyphens of
    Anthropic's own. The 1M context alias ('claude-opus-4-6[1m]') goes: the
    pricing page lists no separate long-context rate for Claude 4.6 and
    later, the models the window comes with. A router's ':free' or
    ':thinking' suffix stays: it names another price, so the id stays
    unpriced, as does any other bracketed suffix.
    """
    bare = BEDROCK_PREFIX.sub("", CONTEXT_ALIAS.sub("", model.rsplit("/", 1)[-1].split("@", 1)[0]))
    return bare.replace(".", "-") if bare.startswith("claude-") else bare


def price_for(model, date=""):
    """The price row for a model id on a date ('YYYY-MM-DD'), or None when
    the table does not know the model. Without a date, the table's row."""
    # Checked on the last path part as written, before price_id drops an
    # '@version' that a suffix may follow, and before the prefix rule, which
    # would read the suffix as a dated tail.
    if ":" in BEDROCK_VERSION.sub("", model.rsplit("/", 1)[-1]):
        return None
    model = price_id(model)
    for key in sorted(PRICE_USD_PER_MTOK, key=len, reverse=True):
        if model == key or (model.startswith(key + "-")
                            and not VARIANT_WORDS.intersection(model[len(key) + 1:].split("-"))):
            row = PRICE_USD_PER_MTOK[key]
            for since, later in PRICE_CHANGES.get(key, ()):
                if date >= since:
                    row = later
            return row
    return None


def cost_estimate(archive_days):
    """Measured usage priced per model and counter at API list prices, in US
    dollars, plus the tokens of any model the table does not know, which are
    left out of the figure rather than priced at a guess."""
    usd, unpriced = 0.0, 0
    for date, day in archive_days.items():
        for model, counters in day["models"].items():
            price = price_for(model, date)
            if price is None:
                unpriced += sum(counters.values())
                continue
            usd += sum(counters[name] * price[name] for name in price) / 1_000_000
    return {"measured_usd": usd, "unpriced_tokens": unpriced}


def source_keys(archive_days):
    """Every source in the archive: the registry's order first, then any key
    this version does not know, alphabetically."""
    present = {key for day in archive_days.values() for key in day}
    known = [s.KEY for s in src.SOURCES if s.KEY in present]
    return known + sorted(present - set(known))


def source_summary(key, entries, churn):
    """One source's measured and estimated tokens per day.

    `entries` are the source's archived records by date and `churn` the lines
    its agents changed by date. A date with a record is measured. A date with
    no record but with such lines is estimated at the source's own
    tokens-per-line ratio. Anything else is left out, which keeps human work,
    and work by agents this source did not measure, unpriced.
    """
    module = src.by_key(key)
    measured_total = sum(tu.source_total(e) for e in entries.values())
    covered = sum(churn.get(date, 0) for date in entries)
    ratio = measured_total / covered if covered else 0.0

    per_day, estimated_total = [], 0
    for date in sorted(set(churn) | set(entries)):
        if date in entries:
            per_day.append([date, tu.source_total(entries[date]), "m"])
            continue
        if not churn[date] or not ratio:
            continue
        tokens = round(ratio * churn[date])
        estimated_total += tokens
        per_day.append([date, tokens, "e"])

    by_model = {}
    for e in entries.values():
        for model, counts in e["models"].items():
            by_model[model] = by_model.get(model, 0) + sum(counts.values())

    return {
        "key": key,
        "label": module.LABEL if module else key,
        "measured_total": measured_total,
        "measured_days": len(entries),
        "estimated_total": estimated_total,
        "ratio": ratio,
        "coverage_start": min(entries) if entries else None,
        "top_model": min(by_model, key=lambda m: (-by_model[m], m)) if by_model else None,
        "per_day": per_day,
    }


def records_with_tokens(archive_days):
    """The archive without records that hold no tokens.

    A record of zero measured nothing: it is neither a measured day nor a
    sign that its agent's commits cost nothing. Archives written before the
    readers dropped zero-usage turns hold such Claude Code records, made of
    its "<synthetic>" turns.
    """
    kept = {}
    for date, day in archive_days.items():
        records = {key: entry for key, entry in day.items() if tu.source_total(entry)}
        if records:
            kept[date] = records
    return kept


def token_summary(archive_days, results):
    """Measured and estimated token usage per day, per source and in total.

    Each source is summarised on its own and the totals are sums over them. A
    date is measured in the combined series only when every source that
    contributed to it measured it: one estimated share makes the total an
    estimate. Classifying per date rather than against a cut-off means a gap
    inside the archived range - a machine change, a run skipped for six weeks -
    needs no special case.
    """
    archive_days = records_with_tokens(archive_days)
    churn = churn_by_date(results)
    keys = source_keys(archive_days)
    entries = {key: {date: day[key] for date, day in archive_days.items() if key in day} for key in keys}
    churns = {key: source_churn_by_date(results, src.by_key(key)) for key in keys}
    sources = [source_summary(key, entries[key], churns[key]) for key in keys]

    combined = {}
    for s in sources:
        for date, tokens, kind in s["per_day"]:
            total, kinds = combined.get(date, (0, set()))
            combined[date] = (total + tokens, kinds | {kind})
    per_day = [[date, total, "m" if kinds == {"m"} else "e"] for date, (total, kinds) in sorted(combined.items())]

    measured_total = sum(s["measured_total"] for s in sources)
    estimated_total = sum(s["estimated_total"] for s in sources)
    lifetime_total = measured_total + estimated_total
    # A source with a rate prices every commit of its agents that changed a
    # line; the blended ratio covers only those sources, so it is the rate the
    # estimates were made at, not diluted by tokens that land on no commit.
    covered = {key: sum(churns[key].get(date, 0) for date in entries[key]) for key in keys}
    rated = [s for s in sources if s["ratio"]]
    covered_ai = sum(covered[s["key"]] for s in rated)
    covered_all = sum(churn.get(date, 0) for date in archive_days)

    counters = {name: 0 for name in WH_PER_1K}
    energy_kwh = co2_kg = cost_usd = lifetime_cost = 0.0
    unpriced = 0
    for s in sources:
        e = entries[s["key"]]
        own = {name: sum(m[name] for d in e.values() for m in d["models"].values()) for name in WH_PER_1K}
        for name, tokens in own.items():
            counters[name] += tokens
        ceiling = s["measured_total"] + s["estimated_total"]
        kwh, kg = energy_estimate(own, s["measured_total"], ceiling)
        energy_kwh += kwh
        co2_kg += kg
        # Like energy, the lifetime cost assumes the measured mix of models and
        # counters held across the estimated era, so it follows the same ceiling.
        cost = cost_estimate(e)
        cost_usd += cost["measured_usd"]
        unpriced += cost["unpriced_tokens"]
        if s["measured_total"]:
            lifetime_cost += cost["measured_usd"] * ceiling / s["measured_total"]
    unmeasured, unmeasured_names = unmeasured_agents(results, {s["key"] for s in rated})

    return {
        "measured_total": measured_total,
        "measured_days": len(archive_days),
        "estimated_total": estimated_total,
        "lifetime_total": lifetime_total,
        "ratio": sum(s["measured_total"] for s in rated) / covered_ai if covered_ai else 0.0,
        "energy_kwh": energy_kwh,
        "co2_kg": co2_kg,
        "cost_usd": cost_usd,
        "lifetime_cost_usd": lifetime_cost,
        "unpriced_tokens": unpriced,
        "cache_read_share": counters["cache_read"] / measured_total if measured_total else 0.0,
        "output_per_line": round(counters["output"] / covered_all) if covered_all else 0,
        "coverage_start": min(archive_days) if archive_days else None,
        "per_day": per_day,
        "sources": sources,
        "unmeasured_agent_commits": unmeasured,
        "unmeasured_agents": unmeasured_names,
    }


def commit_shares(sources, results):
    """(commit index, tokens, kind) for every share of a source's daily tokens.

    The archive knows tokens per day, not per commit, so a source's total for
    a day, measured or estimated alike, is split across the commits its agents
    made that day in proportion to the lines each one changed: the same churn
    the source's ratio is built on. Human and merge commits, and commits by
    agents the source did not measure, get nothing from it, and a day whose
    tokens have no such commits to land on stays unattributed rather than
    being forced onto someone. The kind is the source's own for that day.
    """
    for s in sources:
        module = src.by_key(s["key"])
        if module is None:
            continue
        day_tokens = {date: (tokens, kind) for date, tokens, kind in s["per_day"]}
        by_day = {}
        for r in results:
            if r["date"] in day_tokens and is_ai(r) and src.source_for(r["agent"]) is module:
                churn = churn_of(r)
                if churn:
                    by_day.setdefault(r["date"], []).append((r["index"], churn))
        for date, commits in by_day.items():
            total = sum(churn for _index, churn in commits)
            tokens, kind = day_tokens[date]
            for index, churn in commits:
                yield index, round(tokens * churn / total), kind


def tokens_by_commit(sources, results):
    """Each source's daily tokens attributed to its agents' commits, keyed by commit index."""
    attributed = {}
    for index, tokens, _kind in commit_shares(sources, results):
        attributed[index] = attributed.get(index, 0) + tokens
    return attributed


def token_kinds(sources, results):
    """Whether each attributed commit's share was measured ('m') or estimated
    ('e'). No agent name matches two sources, so a commit has one kind even
    on a day whose combined total mixes both."""
    return {index: kind for index, _tokens, kind in commit_shares(sources, results)}


def unmeasured_agents(results, measured_keys):
    """How many AI-attributed commits carry no token figure, and by whom.

    `measured_keys` are the sources with a rate to price their commits at:
    archived tokens on days their agents changed lines. A commit is
    unmeasured when its agent has no source, or its source has no rate: no
    logs for this repository, logs only for days its agents changed nothing,
    or logs that recorded no tokens. Known sources are named by their label, so a history of
    Claude models reads as "Claude Code".
    """
    count, names = 0, set()
    for r in results:
        if not is_ai(r):
            continue
        source = src.source_for(r["agent"])
        if source is None or source.KEY not in measured_keys:
            count += 1
            names.add(source.LABEL if source else r["agent"])
    return count, sorted(names)


def analyse(repo_dir, output_path, cache_path, archive_path, *, config=None, branch=None,
            max_commits=None, jobs=1, report=None):
    """Analyse `repo_dir` into `output_path` (full_commit_data.json).

    `cache_path` is the per-file cloc cache, `archive_path` the token archive
    (read only; absent is normal). `config` supplies the test rules and agent
    table; `branch` defaults to the checked-out branch; `jobs` is how many
    cloc processes measure commits at once. `report` receives the phase's
    details, warnings, result and summary.
    """
    report = report or ui.Plain(sys.stdout)
    cl.require_cloc()
    repo_dir = paths.find_repo(repo_dir)
    config = config or Config()
    rules, agents = config.rules, config.agents

    branch = branch or git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD").strip()
    # cloc --git takes a working-tree path in preference to a ref of the same
    # name (a `docs` branch beside a docs/ directory), so every cloc call gets
    # the resolved commit, never the bare name.
    rev = git(repo_dir, "rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}").strip()
    if not rev:
        raise NoCommits(f"{repo_dir} has no commits on {branch}")
    # git log, the path history and cloc's per-file report of the branch all
    # run before the first commit is measured, which is minutes on a long
    # history: say so, or a still live line reads as a hang.
    report.status(f"reading the history of {branch}")
    commits = parse_log(repo_dir, rev, agents)
    if not commits:
        raise NoCommits(f"{repo_dir} has no commits on {branch}")
    if is_shallow(repo_dir):
        report.warn("shallow clone; diffs against absent parents will be wrong")

    report.detail("cache", cache_path)
    report.detail("jobs", f"{jobs} cloc at a time")
    show_ext_table = cl.load_extension_table()
    renames, symlinks = path_history(repo_dir, rev)
    # One per-file report of rev serves the language table here and the
    # snapshot in step 3.
    file_report = cl.by_file_report(repo_dir, rev, symlinks)
    learned = cl.learn_extensions(repo_dir, rev, show_ext_table, file_report)
    table = cl.merge_language_tables(show_ext_table, learned)
    table.update({cf.path_key(path): cf.UNCOUNTED for path in symlinks})
    present = {path for path in file_report if path != "header"}
    # One more cloc run counts both sides of every rename, for the names'
    # languages and for the rows that replace cloc's at a language change.
    try:
        counted = cl.count_blobs(repo_dir, [(r.old_blob, r.old) for r in renames] +
                                 [(r.new_blob, r.new) for r in renames])
        uncounted = False
    except (cl.ClocError, OSError, ValueError) as e:
        report.warn(f"could not count the renamed files ({e}); renames that change language will drift")
        # The table's guess instead: a gone old name without an entry takes
        # the language its new name has, newest first so that a chain
        # resolves, unless that is Other; with no counts to replace them by,
        # cloc's rows stay.
        running, guesses = dict(table), []
        for r in renames:
            guess = cf.language_for(r.new, running)
            guess = None if guess in (cf.OTHER, cf.UNCOUNTED) else guess
            if guess and cf.path_key(r.old) not in running and r.old not in present:
                running[cf.path_key(r.old)] = guess
            guesses.append((None, guess))
        counted, uncounted = guesses + guesses, True
    before, after = counted[:len(renames)], counted[len(renames):]
    renamed_names, changed = cf.rename_plan(
        [(r.old, r.new, before[i][1], after[i][1]) for i, r in enumerate(renames)], table, present)
    table.update(renamed_names)
    if uncounted:
        changed = []
    adjustments = cl.rename_adjustments(
        [(renames[i].commit, renames[i].old, renames[i].new, before[i][0], after[i][0]) for i in changed])
    if renames:
        report.detail("renames", f"{len(renames):,}, {len(changed):,} of them changing language")
    # Single files are learned too, under path keys ("/Makefile"); they are not extensions.
    new_extensions = sorted(ext for ext in learned if ext not in show_ext_table and not ext.startswith("/"))
    if new_extensions:
        report.detail("extensions", f"learned {len(new_extensions)} from {branch}: {', '.join(new_extensions)}")
    cache = cl.Cache(cache_path)
    measure_input = [{"hash": c["hash"], "parent": c["parents"][0] if c["parents"] else None,
                      "is_merge": is_merge_commit(c)} for c in commits]
    nonmerge = sum(1 for m in measure_input if not m["is_merge"])
    uncached = sum(1 for m in measure_input if not m["is_merge"] and cache.get(m["hash"]) is None)
    if uncached:
        report.status(f"measuring {uncached:,} new commits with cloc, {jobs} at a time")
    measured = cl.measure_commits(repo_dir, measure_input, cache, table, rules, max_commits=max_commits,
                                  jobs=jobs, report=report, adjustments=adjustments)

    by_lang, by_file_all, by_file_tests = cl.snapshot(repo_dir, rev, table, rules, file_report)

    running_all, running_tests = {}, {}

    def accumulate(target, matrix):
        for lang, row in matrix.items():
            t = target.setdefault(lang, {k: 0 for k in cl.TYPES})
            for i, name in enumerate(cl.TYPES):
                t[name] += row[2 * i] - row[2 * i + 1]

    results = []
    for i, c in enumerate(commits):
        is_merge = is_merge_commit(c)
        if is_merge:
            status, lines, test_lines = "merge", {}, {}
        elif c["hash"] in measured.measured:
            status = "ok"
            lines, test_lines = measured.measured[c["hash"]]
        elif c["hash"] in measured.failed:
            status, lines, test_lines = "failed", {}, {}
        else:
            status, lines, test_lines = "pending", {}, {}
        accumulate(running_all, lines)
        accumulate(running_tests, test_lines)
        results.append({
            "index": i,
            "hash": c["hash"][:7],
            "full_hash": c["hash"],
            "date": c["date"][:10] if c["date"] else "",
            "datetime": c["date"],
            "message": c["message"],
            "body": c["body"].strip(),
            "agent": MISC if is_merge else c["agent"],
            "is_merge": is_merge,
            "status": status,
            "lines": lines,
            "test_lines": test_lines,
        })

    seen = set()
    for r in results:
        seen.update(r["lines"])
        seen.update(r["test_lines"])
    languages = sorted(by_lang, key=lambda l: (-by_lang[l]["code"], l))
    languages += sorted(seen - set(languages))

    def diff(a, b):
        return {lang: {t: a.get(lang, {}).get(t, 0) - b.get(lang, {}).get(t, 0) for t in cl.TYPES}
                for lang in languages}

    reconciliation = diff(running_all, by_lang)
    mapping_check = diff(by_file_all, by_lang)

    first_appearances = {}
    for r in results:
        if r["agent"] and r["agent"] != MISC and r["agent"] not in first_appearances:
            first_appearances[r["agent"]] = {"date": r["date"], "hash": r["hash"], "index": r["index"], "message": r["message"]}

    tokens = token_summary(tu.load(archive_path), results)
    attributed = tokens_by_commit(tokens["sources"], results)
    kinds = token_kinds(tokens["sources"], results)
    for r in results:
        r["tokens"] = attributed.get(r["index"], 0)
        r["token_kind"] = kinds.get(r["index"], "")

    output = {
        "languages": languages,
        "commits": results,
        "first_appearances": first_appearances,
        "summary": {
            "total_commits": len(results),
            "ai_assisted_commits": sum(1 for r in results if r["agent"] and r["agent"] != MISC),
            "human_only_commits": sum(1 for r in results if not r["agent"]),
            "misc_commits": sum(1 for r in results if r["agent"] == MISC),
            "first_date": results[0]["date"],
            "last_date": results[-1]["date"],
            "repo_url": paths.remote_url(repo_dir),
            "analysed_by": paths.build(),
            "head_snapshot": {"all": by_file_all, "tests": by_file_tests},
            "running_totals": {"all": running_all, "tests": running_tests},
            "reconciliation": reconciliation,
            "mapping_check": mapping_check,
            "unmeasured_commits": len(measured.failed),
            "pending_commits": len(measured.pending),
            "tokens": tokens,
        },
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    s = output["summary"]
    if s["unmeasured_commits"]:
        report.warn(f"{s['unmeasured_commits']:,} commits could not be measured by cloc")
    if s["pending_commits"]:
        report.warn(f"{s['pending_commits']:,} commits not yet measured (--max-commits cap); rerun to continue")
    rows, drifting = [], 0
    for lang in languages:
        snap = by_lang.get(lang, {t: 0 for t in cl.TYPES})
        drift, mapping = reconciliation[lang], mapping_check[lang]
        if any(mapping.values()):
            report.warn(f"mapping mismatch for {lang}: {mapping}")
        drifting += any(drift.values())
        rows.append((lang, f"{snap['code']:,}", f"{snap['comment']:,}", f"{snap['blank']:,}",
                     f"{drift['code']:+} / {drift['comment']:+} / {drift['blank']:+}"))
    if drifting:
        report.warn(f"running totals drift from {branch}'s snapshot in {drifting} "
                    f"language{'s' if drifting > 1 else ''} (-v shows the table)")
    new = uncached - len(measured.failed) - len(measured.pending)
    report.done([f"{len(commits):,} commits on {branch} @ {rev[:7]}"],
                f"{new:,} measured, {nonmerge - uncached:,} from cache")
    report.detail("saved", output_path)
    report.summary(ui.summary_rows(s, first_appearances, branch))
    report.table(f"Lines at {branch}", ("", "code", "comment", "blank", "drift"), rows)
    return output
