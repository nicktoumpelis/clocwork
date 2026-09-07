#!/usr/bin/env python3
"""Regenerate index.html by injecting fresh data from full_commit_data.json into the template.

Usage:
    python3 generate_html.py

Reads full_commit_data.json and index.html from the same directory.
Replaces the embedded data blob in index.html with the latest data,
and updates the annotation lines to reflect current first-appearance dates.
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "full_commit_data.json")
HTML_FILE = os.path.join(SCRIPT_DIR, "index.html")
BODIES_FILE = os.path.join(SCRIPT_DIR, "commit_bodies.js")


def build_embedded(data):
    """Compact form of the analysis for the page: matrices become sparse
    [languageIndex, row] pairs so a typical commit carries one or two entries."""
    lang_index = {name: i for i, name in enumerate(data["languages"])}

    def sparse(matrix):
        pairs = [[lang_index[lang], row] for lang, row in matrix.items() if any(row)]
        return sorted(pairs, key=lambda p: p[0])

    commits = [[c["index"], c["hash"], c["date"], c["message"], c["agent"] or "",
                1 if c["is_merge"] else 0, sparse(c["lines"]), sparse(c["test_lines"])]
               for c in data["commits"]]
    return {"languages": data["languages"], "commits": commits, "summary": data["summary"]}


def replace_data_line(html, json_blob):
    """Replace the whole "var RAW = ...;" line with one embedding json_blob.

    Line-anchored so the first "};" in the blob (which a commit subject can
    contain) does not terminate the match early, and a lambda replacement so
    backslashes in the JSON are not interpreted as regex backreferences.
    """
    html, n = re.subn(r"^var RAW = .*;$", lambda _m: f"var RAW = {json_blob};", html, count=1, flags=re.M)
    if n != 1:
        raise SystemExit("index.html: could not find the 'var RAW = ...;' line to replace")
    return html


def main():
    with open(DATA_FILE) as f:
        data = json.load(f)

    with open(HTML_FILE) as f:
        html = f.read()

    # 1. Build compact data blob
    json_blob = json.dumps(build_embedded(data), separators=(",", ":"))

    # 2. Replace the data blob (line starting with "var RAW = ")
    html = replace_data_line(html, json_blob)

    # 3. Update annotation lines from first_appearances
    appearances = data.get("first_appearances", {})

    # Map of annotation IDs to agent names
    annotation_map = {
        "lineOpus45": "Claude Opus 4.5",
        "lineOpus46": "Claude Opus 4.6",
        "lineSonnet45": "Claude Sonnet 4.5",
        "lineOpus46_1m": "Claude Opus 4.6 (1M)",
        "lineOpus47_1m": "Claude Opus 4.7 (1M)",
        "lineOpus48_1m": "Claude Opus 4.8 (1M)",
        "lineFable5": "Claude Fable 5",
        "lineSonnet5": "Claude Sonnet 5",
        "lineOpus5_1m": "Claude Opus 5 (1M)",
        "lineFable51": "Claude Fable 5.1",
    }

    for anno_id, agent_name in annotation_map.items():
        if agent_name in appearances:
            new_date = appearances[agent_name]["date"]
            # Update xMin and xMax for this annotation
            pattern = rf"({anno_id}:\s*\{{[^}}]*?xMin:\s*')[^']*(')"
            html = re.sub(pattern, rf"\g<1>{new_date}\2", html)
            pattern = rf"({anno_id}:\s*\{{[^}}]*?xMax:\s*')[^']*(')"
            html = re.sub(pattern, rf"\g<1>{new_date}\2", html)

    # Handle Sonnet 4.6 combined with Opus 4.6 (1M) if they share a date,
    # or split them if dates diverge
    sonnet46_date = appearances.get("Claude Sonnet 4.6", {}).get("date")
    opus46_1m_date = appearances.get("Claude Opus 4.6 (1M)", {}).get("date")
    if sonnet46_date and opus46_1m_date and sonnet46_date != opus46_1m_date:
        # Update the label to just show Opus 4.6 (1M) since dates differ
        html = html.replace(
            "content: 'Opus 4.6 (1M) + Sonnet 4.6'",
            "content: 'Opus 4.6 (1M)'"
        )

    # 4. Update the footer date and commit count
    today = datetime.now().strftime("%Y-%m-%d")
    total = data["summary"]["total_commits"]
    html = re.sub(
        r"Generated on \d{4}-\d{2}-\d{2} &middot; Full analysis of [\d,]+ commits",
        f"Generated on {today} &middot; Full analysis of {total:,} commits",
        html,
    )

    # 5. Update header subtitle
    first = data["summary"]["first_date"]
    last = data["summary"]["last_date"]
    first_fmt = datetime.strptime(first, "%Y-%m-%d").strftime("%B %Y")
    last_fmt = datetime.strptime(last, "%Y-%m-%d").strftime("%B %Y")
    html = re.sub(
        r"Every commit analysed &middot; [\d,]+ commits from \w+ \d{4} to \w+ \d{4}",
        f"Every commit analysed &middot; {total:,} commits from {first_fmt} to {last_fmt}",
        html,
    )

    # Full commit bodies are large (over a megabyte across the history), so they
    # live in a sidecar script the page loads only when a row is first expanded.
    bodies = {c["hash"]: c["body"] for c in data["commits"] if c.get("body")}
    with open(BODIES_FILE, "w") as f:
        f.write("var COMMIT_BODIES = " + json.dumps(bodies, separators=(",", ":")) + ";\n")

    with open(HTML_FILE, "w") as f:
        f.write(html)

    size_kb = os.path.getsize(HTML_FILE) / 1024
    print(f"Updated {HTML_FILE}")
    print(f"Wrote {BODIES_FILE} ({os.path.getsize(BODIES_FILE) / 1024:.0f} KB, {len(bodies):,} bodies)")
    print(f"  File size: {size_kb:.0f} KB")
    print(f"  Commits: {total:,}")
    print(f"  Date range: {first} to {last}")


if __name__ == "__main__":
    main()
