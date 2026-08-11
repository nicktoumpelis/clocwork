#!/usr/bin/env python3
"""Analyse every commit in one repository's history: cumulative Swift LOC, AI agent detection, biggest jumps.

Usage:
    python3 analyse_all_commits.py [path-to-repo]

If no path is given, defaults to the sibling 'MyApp' directory. The repository
was renamed once (from 'OldApp'); commits from before the
rename are still in this history, so the analysed range spans both names.
"""

import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRIPT_DIR, "..", "MyApp")
REPO_DIR = os.path.abspath(REPO_DIR)
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "full_commit_data.json")

# AI agent patterns (case-insensitive), checked in order (most specific first).
# Within a model family the "(1M context)" variant MUST precede the bare one,
# otherwise the bare pattern would also swallow the 1M commits.
AGENT_PATTERNS = [
    (r"Claude Fable 5", "Claude Fable 5"),
    (r"Claude Opus 4\.8 \(1M context\)", "Claude Opus 4.8 (1M)"),
    (r"Claude Opus 4\.8", "Claude Opus 4.8"),
    (r"Claude Opus 4\.7 \(1M context\)", "Claude Opus 4.7 (1M)"),
    (r"Claude Opus 4\.7", "Claude Opus 4.7"),
    (r"Claude Opus 4\.6 \(1M context\)", "Claude Opus 4.6 (1M)"),
    (r"Claude Opus 4\.6", "Claude Opus 4.6"),
    (r"Claude Opus 4\.5", "Claude Opus 4.5"),
    (r"Claude Sonnet 4\.6", "Claude Sonnet 4.6"),
    (r"Claude Sonnet 4\.5", "Claude Sonnet 4.5"),
    (r"Claude Haiku 4\.5", "Claude Haiku 4.5"),
    (r"Claude", "Claude (unknown version)"),
]


def git(*args):
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=REPO_DIR
    )
    return result.stdout


def detect_agent(body):
    if not body:
        return None
    for pattern, name in AGENT_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return name
    return None


def main():
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        print(f"Error: {REPO_DIR} is not a git repository")
        sys.exit(1)

    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    print(f"Analysing repo: {REPO_DIR} (branch: {branch})")
    print("Step 1: Extracting full commit history with numstat...")

    raw = git(
        "log", branch, "--reverse",
        "--format=COMMIT_START%n%H%n%aI%n%s%n%b%nCOMMIT_BODY_END",
        "--numstat"
    )

    commits = []
    current = None
    in_body = False
    body_lines = []

    for line in raw.splitlines():
        if line == "COMMIT_START":
            if current is not None:
                current["body"] = "\n".join(body_lines)
                current["agent"] = detect_agent(current["body"])
                commits.append(current)
            current = {"numstat": []}
            body_lines = []
            in_body = True
            field_idx = 0
            continue

        if current is None:
            continue

        if in_body and field_idx < 3:
            if field_idx == 0:
                current["hash"] = line.strip()
            elif field_idx == 1:
                current["date"] = line.strip()
            elif field_idx == 2:
                current["message"] = line.strip()
            field_idx += 1
            continue

        if line == "COMMIT_BODY_END":
            in_body = False
            continue

        if in_body:
            body_lines.append(line)
            continue

        parts = line.split("\t")
        if len(parts) == 3:
            add_str, del_str, filename = parts
            if add_str != "-" and del_str != "-":
                current["numstat"].append({
                    "additions": int(add_str),
                    "deletions": int(del_str),
                    "file": filename,
                })

    if current is not None:
        current["body"] = "\n".join(body_lines)
        current["agent"] = detect_agent(current["body"])
        commits.append(current)

    print(f"  Parsed {len(commits)} commits")

    print("Step 2: Computing cumulative Swift LOC for every commit...")
    cumulative_swift = 0
    cumulative_total = 0
    results = []

    for i, c in enumerate(commits):
        swift_add = 0
        swift_del = 0
        total_add = 0
        total_del = 0
        swift_files_changed = 0

        for ns in c["numstat"]:
            total_add += ns["additions"]
            total_del += ns["deletions"]
            if ns["file"].endswith(".swift"):
                swift_add += ns["additions"]
                swift_del += ns["deletions"]
                swift_files_changed += 1

        swift_delta = swift_add - swift_del
        total_delta = total_add - total_del
        cumulative_swift += swift_delta
        cumulative_total += total_delta

        date_str = c["date"][:10] if c["date"] else ""

        results.append({
            "index": i,
            "hash": c["hash"][:7],
            "full_hash": c["hash"],
            "date": date_str,
            "datetime": c["date"],
            "message": c["message"][:120],
            "agent": c["agent"],
            "swift_added": swift_add,
            "swift_deleted": swift_del,
            "swift_delta": swift_delta,
            "swift_cumulative": cumulative_swift,
            "total_added": total_add,
            "total_deleted": total_del,
            "total_delta": total_delta,
            "total_cumulative": cumulative_total,
            "swift_files_changed": swift_files_changed,
            "is_merge": c["message"].startswith("Merge pull request"),
        })

        if (i + 1) % 200 == 0:
            print(f"  Processed {i + 1}/{len(commits)} commits...")

    print("Step 3: Identifying biggest jumps...")
    non_merge = [r for r in results if not r["is_merge"]]
    biggest_gains = sorted(non_merge, key=lambda x: x["swift_delta"], reverse=True)[:25]
    biggest_drops = sorted(non_merge, key=lambda x: x["swift_delta"])[:15]

    print("Step 4: Computing agent statistics...")
    agent_stats = {}
    for r in results:
        agent = r["agent"] or "Human"
        if agent not in agent_stats:
            agent_stats[agent] = {
                "commits": 0, "swift_added": 0, "swift_deleted": 0,
                "swift_net": 0, "first_date": r["date"], "last_date": r["date"],
            }
        stats = agent_stats[agent]
        stats["commits"] += 1
        stats["swift_added"] += r["swift_added"]
        stats["swift_deleted"] += r["swift_deleted"]
        stats["swift_net"] += r["swift_delta"]
        stats["last_date"] = r["date"]

    print("Step 5: Computing daily aggregates...")
    daily = {}
    for r in results:
        d = r["date"]
        if d not in daily:
            daily[d] = {
                "date": d, "swift_cumulative": 0, "total_cumulative": 0,
                "commits": 0, "swift_delta": 0, "agents": {},
            }
        daily[d]["swift_cumulative"] = r["swift_cumulative"]
        daily[d]["total_cumulative"] = r["total_cumulative"]
        daily[d]["commits"] += 1
        daily[d]["swift_delta"] += r["swift_delta"]
        a = r["agent"] or "Human"
        daily[d]["agents"][a] = daily[d]["agents"].get(a, 0) + 1

    daily_list = sorted(daily.values(), key=lambda x: x["date"])

    print("Step 6: Finding first agent appearances...")
    first_appearances = {}
    for r in results:
        if r["agent"] and r["agent"] not in first_appearances:
            first_appearances[r["agent"]] = {
                "date": r["date"],
                "hash": r["hash"],
                "index": r["index"],
                "swift_cumulative": r["swift_cumulative"],
                "message": r["message"],
            }

    output = {
        "commits": results,
        "daily": daily_list,
        "biggest_gains": biggest_gains,
        "biggest_drops": biggest_drops,
        "agent_stats": agent_stats,
        "first_appearances": first_appearances,
        "summary": {
            "total_commits": len(results),
            "ai_assisted_commits": sum(1 for r in results if r["agent"]),
            "human_only_commits": sum(1 for r in results if not r["agent"]),
            "final_swift_loc": cumulative_swift,
            "final_total_loc": cumulative_total,
            "first_date": results[0]["date"],
            "last_date": results[-1]["date"],
            "peak_swift_loc": max(r["swift_cumulative"] for r in results),
            "peak_swift_date": max(results, key=lambda r: r["swift_cumulative"])["date"],
            "peak_swift_hash": max(results, key=lambda r: r["swift_cumulative"])["hash"],
        }
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Saved to {OUTPUT_FILE}")
    print(f"  Total commits: {len(results)}")
    print(f"  AI-assisted: {output['summary']['ai_assisted_commits']}")
    print(f"  Human-only: {output['summary']['human_only_commits']}")
    print(f"  Final Swift LOC: {cumulative_swift:,}")
    print(f"  Peak Swift LOC: {output['summary']['peak_swift_loc']:,} ({output['summary']['peak_swift_date']})")
    print(f"\n  Agent breakdown:")
    for agent, stats in sorted(agent_stats.items(), key=lambda x: -x[1]["commits"]):
        print(f"    {agent}: {stats['commits']} commits, net {stats['swift_net']:+,} Swift LOC")
    print(f"\n  First appearances:")
    for agent, info in sorted(first_appearances.items(), key=lambda x: x[1]["index"]):
        print(f"    {agent}: {info['date']} ({info['hash']})")


if __name__ == "__main__":
    main()
