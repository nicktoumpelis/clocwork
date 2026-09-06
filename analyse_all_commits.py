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
DEFAULT_REPO = os.path.join(SCRIPT_DIR, "..", "MyApp")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "full_commit_data.json")
CACHE_FILE = os.path.join(SCRIPT_DIR, "cloc_cache.json")

# AI agent detection.
#
# Attribution is read from "Co-Authored-By:" trailer lines only, so a human
# commit that merely mentions CLAUDE.md or a claude-* branch name is not
# counted as AI-assisted.
#
# Model names are parsed generically rather than listed one by one, so any
# Claude model - past, present, or future - is recognised without a code
# change. Two naming schemes are handled:
#
#   family-first (Claude 4+):  "Claude Opus 4.6", "Claude Fable 5.1",
#                              "Claude Opus 5 (1M context)"
#   version-first (Claude 3.x): "Claude 3.5 Sonnet", "Claude 3 Opus"
#
# Both normalise to "Claude <Family> <version>", with " (1M)" appended for the
# 1M-context variants, so the dashboard sees one consistent naming scheme.
# The version is captured greedily, which is what keeps "Fable 5.1" from being
# read as "Fable 5".
CLAUDE_FAMILIES = r"(?:Fable|Opus|Sonnet|Haiku|Mythos)"
CLAUDE_VERSION = r"\d+(?:\.\d+)?"
CLAUDE_CONTEXT = r"(?:\s*\((\d+[KM]) context\))?"

MODEL_FAMILY_FIRST = re.compile(
    rf"Claude\s+({CLAUDE_FAMILIES})\s+({CLAUDE_VERSION}){CLAUDE_CONTEXT}",
    re.IGNORECASE,
)
MODEL_VERSION_FIRST = re.compile(
    rf"Claude\s+({CLAUDE_VERSION})\s+({CLAUDE_FAMILIES}){CLAUDE_CONTEXT}",
    re.IGNORECASE,
)
COAUTHOR_TRAILER = re.compile(r"^\s*Co-Authored-By:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

UNKNOWN_CLAUDE = "Claude (unknown version)"

# Merge commits (GitHub "Merge pull request ..." commits) carry no code of
# their own, so they are filed under a catch-all category rather than being
# attributed to a human or an AI agent.
MISC = "Misc"


def normalise_model(family, version, context):
    name = f"Claude {family.capitalize()} {version}"
    if context:
        name += f" ({context.upper()})"
    return name


def parse_claude_model(text):
    """Return the normalised Claude model name found in a co-author trailer, or None."""
    m = MODEL_FAMILY_FIRST.search(text)
    if m:
        return normalise_model(m.group(1), m.group(2), m.group(3))
    m = MODEL_VERSION_FIRST.search(text)
    if m:
        return normalise_model(m.group(2), m.group(1), m.group(3))
    if re.search(r"\bClaude\b", text, re.IGNORECASE):
        return UNKNOWN_CLAUDE
    return None


def git(repo, *args):
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=repo)
    return result.stdout


def github_url(repo):
    """Return the https URL of the origin remote if it is on GitHub, else None."""
    remote = git(repo, "remote", "get-url", "origin").strip()
    m = re.match(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", remote)
    return f"https://github.com/{m.group(1)}" if m else None


def detect_agent(body):
    """Detect the AI agent credited in a commit body via its Co-Authored-By trailers.

    The first Claude trailer wins, matching the previous first-match behaviour
    for commits that credit more than one model.
    """
    if not body:
        return None
    for trailer in COAUTHOR_TRAILER.findall(body):
        model = parse_claude_model(trailer)
        if model:
            return model
    return None


def parse_log(repo, branch):
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
        c["agent"] = detect_agent(c["body"])
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


def analyse(repo_dir, output_path, cache_path=None, max_commits=None, log=print):
    branch = git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD").strip()
    log(f"Analysing repo: {repo_dir} (branch: {branch})")
    log("Step 1: Extracting full commit history with numstat...")

    commits = parse_log(repo_dir, branch)

    log(f"  Parsed {len(commits)} commits")

    log("Step 2: Computing cumulative Swift LOC for every commit...")
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
        is_merge = c["message"].startswith("Merge pull request")
        agent = MISC if is_merge else c["agent"]

        results.append({
            "index": i,
            "hash": c["hash"][:7],
            "full_hash": c["hash"],
            "date": date_str,
            "datetime": c["date"],
            "message": c["message"],
            "body": c["body"].strip(),
            "agent": agent,
            "swift_added": swift_add,
            "swift_deleted": swift_del,
            "swift_delta": swift_delta,
            "swift_cumulative": cumulative_swift,
            "total_added": total_add,
            "total_deleted": total_del,
            "total_delta": total_delta,
            "total_cumulative": cumulative_total,
            "swift_files_changed": swift_files_changed,
            "is_merge": is_merge,
        })

        if (i + 1) % 200 == 0:
            log(f"  Processed {i + 1}/{len(commits)} commits...")

    log("Step 3: Identifying biggest jumps...")
    non_merge = [r for r in results if not r["is_merge"]]
    biggest_gains = sorted(non_merge, key=lambda x: x["swift_delta"], reverse=True)[:25]
    biggest_drops = sorted(non_merge, key=lambda x: x["swift_delta"])[:15]

    log("Step 4: Computing agent statistics...")
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

    log("Step 5: Computing daily aggregates...")
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

    log("Step 6: Finding first agent appearances...")
    first_appearances = {}
    for r in results:
        if r["agent"] and r["agent"] != MISC and r["agent"] not in first_appearances:
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
            "ai_assisted_commits": sum(1 for r in results if r["agent"] and r["agent"] != MISC),
            "human_only_commits": sum(1 for r in results if not r["agent"]),
            "misc_commits": sum(1 for r in results if r["agent"] == MISC),
            "final_swift_loc": cumulative_swift,
            "final_total_loc": cumulative_total,
            "first_date": results[0]["date"],
            "last_date": results[-1]["date"],
            "peak_swift_loc": max(r["swift_cumulative"] for r in results),
            "peak_swift_date": max(results, key=lambda r: r["swift_cumulative"])["date"],
            "peak_swift_hash": max(results, key=lambda r: r["swift_cumulative"])["hash"],
            "repo_url": github_url(repo_dir),
        }
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    log(f"\nDone! Saved to {output_path}")
    log(f"  Total commits: {len(results)}")
    log(f"  AI-assisted: {output['summary']['ai_assisted_commits']}")
    log(f"  Human-only: {output['summary']['human_only_commits']}")
    log(f"  Misc (merges): {output['summary']['misc_commits']}")
    log(f"  Final Swift LOC: {cumulative_swift:,}")
    log(f"  Peak Swift LOC: {output['summary']['peak_swift_loc']:,} ({output['summary']['peak_swift_date']})")
    log(f"\n  Agent breakdown:")
    for agent, stats in sorted(agent_stats.items(), key=lambda x: -x[1]["commits"]):
        log(f"    {agent}: {stats['commits']} commits, net {stats['swift_net']:+,} Swift LOC")
    log(f"\n  First appearances:")
    for agent, info in sorted(first_appearances.items(), key=lambda x: x[1]["index"]):
        log(f"    {agent}: {info['date']} ({info['hash']})")

    return output


def main():
    repo = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"Error: {repo} is not a git repository")
        sys.exit(1)
    max_commits = os.environ.get("CLOC_MAX_COMMITS")
    analyse(repo, OUTPUT_FILE, CACHE_FILE, int(max_commits) if max_commits else None)


if __name__ == "__main__":
    main()
