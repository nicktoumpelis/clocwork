#!/usr/bin/env python3
"""Analyse every commit in a repository's history: lines per language and type
via cloc, AI agent detection, and token usage from the transcript archive.

The repository, the output path, the cache, the archive and the classification
rules are all inputs; nothing here knows which repository it is measuring.
"""

import json
import os
import subprocess

from clocwork import cloc as cl
from clocwork import paths
from clocwork import tokens as tu
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
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=repo)
    return result.stdout


def is_shallow(repo):
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def parse_log(repo, branch, agents=DEFAULT_AGENTS):
    """Return every commit reachable from branch, oldest first, with parents, body, numstat and agent."""
    raw = git(repo, "log", branch, "--reverse",
              "--format=COMMIT_START%n%H%n%P%n%aI%n%s%n%b%nCOMMIT_BODY_END", "--numstat")
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


def churn_by_date(results):
    """Lines added plus removed per date, and the AI-attributed share of them.

    Merge commits carry no line matrices, so they contribute nothing here, as
    everywhere else in this project.
    """
    totals = {}
    for r in results:
        if not r["date"]:
            continue
        entry = totals.setdefault(r["date"], {"churn": 0, "ai_churn": 0})
        churn = sum(sum(row) for row in r["lines"].values())
        entry["churn"] += churn
        if r["agent"] and r["agent"] != MISC:
            entry["ai_churn"] += churn
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


# API list prices in US dollars per million tokens, from
# platform.claude.com/docs/en/about-claude/pricing on 2026-09-07. Cache writes
# are priced at the one-hour rate: Claude Code writes its cache with that TTL
# (98% of cache-write tokens in the current transcripts) and the archive keeps
# one cache-write counter. Long context carries no premium on these models.
# Keys are matched as prefixes, longest first, so dated ids and whole
# generations ('claude-opus-4-6') resolve without a row each.
PRICE_USD_PER_MTOK = {
    "claude-fable-5-1": {"input": 10.0, "cache_write": 20.0, "cache_read": 0.25, "output": 50.0},
    "claude-fable-5":   {"input": 10.0, "cache_write": 20.0, "cache_read": 1.0,  "output": 50.0},
    "claude-opus-5":    {"input": 5.0,  "cache_write": 10.0, "cache_read": 0.5,  "output": 25.0},
    "claude-opus-4-1":  {"input": 15.0, "cache_write": 30.0, "cache_read": 1.5,  "output": 75.0},
    "claude-opus-4":    {"input": 5.0,  "cache_write": 10.0, "cache_read": 0.5,  "output": 25.0},
    "claude-sonnet-5":  {"input": 2.0,  "cache_write": 4.0,  "cache_read": 0.2,  "output": 10.0},
    "claude-sonnet-4":  {"input": 3.0,  "cache_write": 6.0,  "cache_read": 0.3,  "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0,  "cache_write": 2.0,  "cache_read": 0.1,  "output": 5.0},
}


def price_for(model):
    """The price row for a model id, or None when the table does not know it."""
    for key in sorted(PRICE_USD_PER_MTOK, key=len, reverse=True):
        if model == key or model.startswith(key + "-"):
            return PRICE_USD_PER_MTOK[key]
    return None


def cost_estimate(archive_days):
    """Measured usage priced per model and counter at API list prices, in US
    dollars, plus the tokens of any model the table does not know, which are
    left out of the figure rather than priced at a guess."""
    usd, unpriced = 0.0, 0
    for day in archive_days.values():
        for model, counters in day["models"].items():
            price = price_for(model)
            if price is None:
                unpriced += sum(counters.values())
                continue
            usd += sum(counters[name] * price[name] for name in price) / 1_000_000
    return {"measured_usd": usd, "unpriced_tokens": unpriced}


def token_summary(archive_days, results):
    """Measured and estimated token usage per day.

    A date with an archive record is measured. A date with AI-attributed churn
    and no record is estimated at the archive's tokens-per-line ratio. A date
    with neither is left out entirely, which is what keeps the pre-2026 human
    era off the chart rather than pricing it.

    Classifying per date rather than against a cut-off means a gap inside the
    archived range - a machine change, a run skipped for six weeks - needs no
    special case.
    """
    churn = churn_by_date(results)
    measured_total = sum(tu.day_total(d) for d in archive_days.values())
    covered_ai = sum(churn.get(date, {}).get("ai_churn", 0) for date in archive_days)
    covered_all = sum(churn.get(date, {}).get("churn", 0) for date in archive_days)
    ratio = measured_total / covered_ai if covered_ai else 0.0

    per_day, estimated_total = [], 0
    for date in sorted(set(churn) | set(archive_days)):
        if date in archive_days:
            per_day.append([date, tu.day_total(archive_days[date]), "m"])
            continue
        ai = churn.get(date, {}).get("ai_churn", 0)
        if not ai or not ratio:
            continue
        tokens = round(ratio * ai)
        estimated_total += tokens
        per_day.append([date, tokens, "e"])

    def counter(name):
        return sum(m[name] for d in archive_days.values() for m in d["models"].values())

    lifetime_total = measured_total + estimated_total
    counters = {name: counter(name) for name in WH_PER_1K}
    energy_kwh, co2_kg = energy_estimate(counters, measured_total, lifetime_total)
    # Like energy, the lifetime cost assumes the measured mix of models and
    # counters held across the estimated era, so it follows the same ceiling.
    cost = cost_estimate(archive_days)
    lifetime_cost = cost["measured_usd"] * lifetime_total / measured_total if measured_total else 0.0

    return {
        "measured_total": measured_total,
        "measured_days": len(archive_days),
        "estimated_total": estimated_total,
        "lifetime_total": lifetime_total,
        "ratio": ratio,
        "energy_kwh": energy_kwh,
        "co2_kg": co2_kg,
        "cost_usd": cost["measured_usd"],
        "lifetime_cost_usd": lifetime_cost,
        "unpriced_tokens": cost["unpriced_tokens"],
        "cache_read_share": counter("cache_read") / measured_total if measured_total else 0.0,
        "output_per_line": round(counter("output") / covered_all) if covered_all else 0,
        "coverage_start": min(archive_days) if archive_days else None,
        "per_day": per_day,
    }


def tokens_by_commit(per_day, results):
    """Each day's tokens attributed to that day's AI commits, keyed by commit index.

    The archive knows tokens per day, not per commit, so a day's total, measured
    or estimated alike, is split across the AI-attributed commits of that day in
    proportion to the lines each one changed: the same churn the estimator's
    ratio is built on. Human and merge commits get nothing, and a day whose
    tokens have no AI churn to land on stays unattributed rather than being
    forced onto someone.
    """
    day_tokens = {date: tokens for date, tokens, _kind in per_day}
    by_day = {}
    for r in results:
        if r["date"] in day_tokens and r["agent"] and r["agent"] != MISC:
            churn = sum(sum(row) for row in r["lines"].values())
            if churn:
                by_day.setdefault(r["date"], []).append((r["index"], churn))
    attributed = {}
    for date, commits in by_day.items():
        total = sum(churn for _index, churn in commits)
        for index, churn in commits:
            attributed[index] = round(day_tokens[date] * churn / total)
    return attributed


def analyse(repo_dir, output_path, cache_path, archive_path, *, config=None, branch=None,
            max_commits=None, log=print):
    """Analyse `repo_dir` into `output_path` (full_commit_data.json).

    `cache_path` is the per-file cloc cache, `archive_path` the token archive
    (read only; absent is normal). `config` supplies the test rules and agent
    table; `branch` defaults to the checked-out branch.
    """
    cl.require_cloc()
    repo_dir = paths.find_repo(repo_dir)
    config = config or Config()
    rules, agents = config.rules, config.agents

    branch = branch or git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD").strip()
    log(f"Analysing repo: {repo_dir} (branch: {branch})")
    log("Step 1: Extracting full commit history...")
    commits = parse_log(repo_dir, branch, agents)
    if not commits:
        raise NoCommits(f"{repo_dir} has no commits on {branch}")
    log(f"  Parsed {len(commits)} commits")
    if is_shallow(repo_dir):
        log("  WARNING: shallow clone; diffs against absent parents will be wrong")

    log(f"Step 2: Measuring lines per commit with cloc (cache: {cache_path})...")
    show_ext_table = cl.load_extension_table()
    learned = cl.learn_extensions(repo_dir, "HEAD")
    table = cl.merge_language_tables(show_ext_table, learned)
    new_extensions = sorted(ext for ext in learned if ext not in show_ext_table)
    if new_extensions:
        log(f"  learned {len(new_extensions)} extensions from HEAD: {', '.join(new_extensions)}")
    cache = cl.Cache(cache_path)
    measure_input = [{"hash": c["hash"], "parent": c["parents"][0] if c["parents"] else None,
                      "is_merge": is_merge_commit(c)} for c in commits]
    log(f"  {sum(1 for m in measure_input if not m['is_merge'] and cache.get(m['hash']) is None)} commits not yet cached")
    measured = cl.measure_commits(repo_dir, measure_input, cache, table, rules, max_commits=max_commits, log=log)

    log("Step 3: Snapshot of HEAD for reconciliation...")
    by_lang, by_file_all, by_file_tests = cl.snapshot(repo_dir, "HEAD", table, rules)

    log("Step 4: Building per-commit records and running totals...")
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

    log("Step 5: Finding first agent appearances...")
    first_appearances = {}
    for r in results:
        if r["agent"] and r["agent"] != MISC and r["agent"] not in first_appearances:
            first_appearances[r["agent"]] = {"date": r["date"], "hash": r["hash"], "index": r["index"], "message": r["message"]}

    tokens = token_summary(tu.load(archive_path), results)
    attributed = tokens_by_commit(tokens["per_day"], results)
    for r in results:
        r["tokens"] = attributed.get(r["index"], 0)

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
    log(f"\nDone! Saved to {output_path}")
    log(f"  Total commits: {s['total_commits']}  (AI-assisted {s['ai_assisted_commits']}, human-only {s['human_only_commits']}, misc {s['misc_commits']})")
    if s["unmeasured_commits"]:
        log(f"  WARNING: {s['unmeasured_commits']} commits could not be measured by cloc")
    if s["pending_commits"]:
        log(f"  NOTE: {s['pending_commits']} commits not yet measured (--max-commits cap); rerun to continue")
    t = s["tokens"]
    if t["measured_total"]:
        log(f"  Tokens: {t['lifetime_total']:,} lifetime "
            f"({t['measured_total']:,} measured over {t['measured_days']} days, "
            f"{t['estimated_total']:,} estimated at {t['ratio']:,.0f} per AI line)")
    else:
        log("  Tokens: none (no Claude Code transcript archive for this repository)")
    head_tests = sum(v["code"] for v in by_file_tests.values())
    head_all = sum(v["code"] for v in by_file_all.values())
    log(f"  Test code at HEAD: {head_tests:,} of {head_all:,} code lines ({head_tests / head_all:.1%})"
        if head_all else "  Test code at HEAD: none")
    log("  Lines at HEAD (cloc snapshot) and drift of running totals:")
    for lang in languages:
        snap = by_lang.get(lang, {t: 0 for t in cl.TYPES})
        drift = reconciliation[lang]
        mapping = mapping_check[lang]
        log(f"    {lang:<16} code {snap['code']:>8,} comment {snap['comment']:>8,} blank {snap['blank']:>8,}"
            f"   drift {drift['code']:+} / {drift['comment']:+} / {drift['blank']:+}"
            + (f"   MAPPING MISMATCH {mapping}" if any(mapping.values()) else ""))
    log("  First appearances:")
    for agent, info in sorted(first_appearances.items(), key=lambda x: x[1]["index"]):
        log(f"    {agent}: {info['date']} ({info['hash']})")
    return output
