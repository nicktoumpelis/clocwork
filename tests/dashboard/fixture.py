"""Write a synthetic clocwork workspace for the dashboard tests.

Usage: python3 tests/dashboard/fixture.py <workspace-dir>

Deterministic: the same numbers every run, so the checks in tests/dashboard
can reason about the data they are given. Shaped like a real
full_commit_data.json: 520 commits so the 500-row cap is exercised, three
languages, four agents including the merge category, measured and estimated
token days, commit bodies for the expander, and a GitHub remote for the links.
When analyse.py changes the output shape, change this file in the same commit.
"""
import json
import os
import random
import sys
from datetime import date, timedelta

LANGS = ["Swift", "Markdown", "Python"]
AGENTS = [None, None, "Claude Opus 4.6", "Claude Fable 5.1", "Copilot"]
TYPES = ("code", "comment", "blank")
# Message vocabulary; "font" is what tests/dashboard/test_table.js searches for.
WORDS = ["layout", "font", "sync", "reminder", "widget", "font size", "colour"]
REMOTE = "https://github.com/example/fixture"


def matrix(rng, scale):
    return [rng.randint(0, scale), rng.randint(0, scale // 3), rng.randint(0, scale // 4),
            rng.randint(0, scale // 8), rng.randint(0, scale // 6), rng.randint(0, scale // 10)]


def build():
    rng = random.Random(20260915)
    start = date(2025, 1, 1)
    commits, running, running_tests = [], {}, {}
    for i in range(520):
        day = start + timedelta(days=i // 2)
        is_merge = i % 40 == 39
        agent = "Misc" if is_merge else (AGENTS[i % len(AGENTS)] if i > 60 else None)
        lines, tests = {}, {}
        if not is_merge:
            for lang in LANGS:
                if rng.random() < 0.6:
                    row = matrix(rng, 200 if lang == "Swift" else 40)
                    lines[lang] = row
                    if rng.random() < 0.3:
                        tests[lang] = [v // 3 for v in row]
        for target, m in ((running, lines), (running_tests, tests)):
            for lang, row in m.items():
                t = target.setdefault(lang, {k: 0 for k in TYPES})
                for k, name in enumerate(TYPES):
                    t[name] += row[2 * k] - row[2 * k + 1]
        commits.append({
            "index": i, "hash": f"{i:07x}", "full_hash": f"{i:040x}", "date": day.isoformat(),
            "datetime": day.isoformat() + "T10:00:00+00:00",
            "message": f"Merge pull request #{i} from example/branch-{i}" if is_merge else f"Change {i}: adjust {WORDS[i % len(WORDS)]}",
            "body": f"Body of change {i}\n\nCo-Authored-By: {agent} <a@b>" if agent and not is_merge and i % 3 == 0 else "",
            "agent": agent, "is_merge": is_merge, "status": "merge" if is_merge else "ok",
            "lines": lines, "test_lines": tests, "tokens": 0,
        })
    first = {}
    for c in commits:
        if c["agent"] and c["agent"] != "Misc" and c["agent"] not in first:
            first[c["agent"]] = {"date": c["date"], "hash": c["hash"], "index": c["index"], "message": c["message"]}
    days = sorted({c["date"] for c in commits if c["date"] >= first[min(first, key=lambda a: first[a]["index"])]["date"]})
    cut = len(days) // 2
    per_day = [[d, 12_000_000 if i % 2 else 5_000_000, "m" if i >= cut else "e"] for i, d in enumerate(days)]
    measured = sum(t for _, t, k in per_day if k == "m")
    estimated = sum(t for _, t, k in per_day if k == "e")
    day_tokens = {d: t for d, t, _ in per_day}
    for c in commits:
        if c["agent"] and c["agent"] != "Misc" and c["date"] in day_tokens:
            c["tokens"] = day_tokens[c["date"]] // 3
    zero = {lang: {k: 0 for k in TYPES} for lang in LANGS}
    ai = sum(1 for c in commits if c["agent"] and c["agent"] != "Misc")
    return {
        "languages": LANGS, "commits": commits, "first_appearances": first,
        "summary": {
            "total_commits": len(commits), "ai_assisted_commits": ai,
            "human_only_commits": sum(1 for c in commits if not c["agent"]),
            "misc_commits": sum(1 for c in commits if c["agent"] == "Misc"),
            "first_date": commits[0]["date"], "last_date": commits[-1]["date"],
            "repo_url": REMOTE,
            "head_snapshot": {"all": running, "tests": running_tests},
            "running_totals": {"all": running, "tests": running_tests},
            "reconciliation": zero, "mapping_check": zero,
            "unmeasured_commits": 0, "pending_commits": 0,
            "tokens": {
                "measured_total": measured, "measured_days": sum(1 for r in per_day if r[2] == "m"),
                "estimated_total": estimated, "lifetime_total": measured + estimated, "ratio": 812.5,
                "energy_kwh": 1234.5, "co2_kg": 493.8, "cost_usd": 4321.0, "lifetime_cost_usd": 9876.0,
                "unpriced_tokens": 0, "cache_read_share": 0.913, "output_per_line": 42,
                "coverage_start": per_day[cut][0], "per_day": per_day,
            },
        },
    }


def main():
    ws = sys.argv[1]
    os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "full_commit_data.json"), "w") as f:
        json.dump(build(), f)
    with open(os.path.join(ws, "clocwork.json"), "w") as f:
        json.dump({"version": "0.1.0", "repo_remote": REMOTE, "repo_path": "/example/fixture",
                   "repo_name": "fixture", "generated": "2026-09-15T00:00:00Z"}, f)
        f.write("\n")


if __name__ == "__main__":
    main()
