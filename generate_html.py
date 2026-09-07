#!/usr/bin/env python3
"""Regenerate index.html by injecting fresh data from full_commit_data.json into the template.

Usage:
    python3 generate_html.py

Reads full_commit_data.json and index.html from the same directory.
Replaces the embedded data blob in index.html with the latest data,
and updates the annotation lines to reflect current first-appearance dates.
The header and footer figures (commit count, date range, generation date) are
not written here: the page renders them from the blob, formatted for the region
locale recorded by detect_locale() below.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "full_commit_data.json")
HTML_FILE = os.path.join(SCRIPT_DIR, "index.html")
BODIES_FILE = os.path.join(SCRIPT_DIR, "commit_bodies.js")


# ICU keyword -> BCP 47 Unicode extension key, for the customisations macOS
# appends to AppleLocale (e.g. "en_SE@calendar=japanese"). Intl understands the
# same settings only in -u- form, and ignores keys it has no use for.
ICU_KEYS = {"calendar": "ca", "collation": "co", "currency": "cu", "fw": "fw", "hours": "hc",
            "ms": "ms", "numbers": "nu", "rg": "rg", "timezone": "tz"}
ICU_VALUES = {"gregorian": "gregory"}


def bcp47(tag):
    """A POSIX or Apple locale identifier as the BCP 47 tag Intl accepts:
    'en_SE.UTF-8' -> 'en-SE', 'en_SE@calendar=japanese' -> 'en-SE-u-ca-japanese'.
    C and POSIX are not locales and give None."""
    base, _, keywords = (tag or "").strip().split(".")[0].partition("@")
    base = base.strip().replace("_", "-")
    if not base or base.upper() in ("C", "POSIX"):
        return None
    ext = []
    for pair in keywords.split(";"):
        key, _, value = pair.partition("=")
        key, value = key.strip().lower(), value.strip().lower()
        if key in ICU_KEYS and value:
            ext.append(ICU_KEYS[key] + "-" + ICU_VALUES.get(value, value))
    return base + ("-u-" + "-".join(ext) if ext else "")


def with_extension(tag, key, value):
    """`tag` with the Unicode extension `key` set to `value`, replacing any existing one."""
    base, _, ext = tag.partition("-u-")
    parts = ext.split("-") if ext else []
    pairs = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
    pairs = [(k, v) for k, v in pairs if k != key] + [(key, value)]
    return base + "-u-" + "-".join(k + "-" + v for k, v in pairs)


def read_default(key):
    """A macOS global default as a string, '' when unset or not on macOS."""
    try:
        out = subprocess.run(["defaults", "read", "-g", key], capture_output=True, text=True)
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def detect_locale(env=os.environ, platform=sys.platform, apple=read_default):
    """The region locale the page should format with, or None.

    Browsers expose only the language list, never the OS region, so the machine
    generating the page records it. An explicit CLOC_LOCALE wins; then the macOS
    region setting, with the measurement-system setting carried as a -u-ms-
    extension when it has been set explicitly; then the POSIX locale variables."""
    explicit = bcp47(env.get("CLOC_LOCALE"))
    if explicit:
        return explicit
    if platform == "darwin":
        tag = bcp47(apple("AppleLocale"))
        if tag:
            metric = apple("AppleMetricUnits")
            if metric in ("0", "1"):
                tag = with_extension(tag, "ms", "metric" if metric == "1" else "ussystem")
            return tag
    for var in ("LC_ALL", "LC_NUMERIC", "LANG"):
        tag = bcp47(env.get(var))
        if tag:
            return tag
    return None


def build_embedded(data, generated, locale):
    """Compact form of the analysis for the page: matrices become sparse
    [languageIndex, row] pairs so a typical commit carries one or two entries.

    `generated` is the ISO date of this run and `locale` the region locale to
    format everything with (None leaves the page to the browser's languages)."""
    lang_index = {name: i for i, name in enumerate(data["languages"])}

    def sparse(matrix):
        pairs = [[lang_index[lang], row] for lang, row in matrix.items() if any(row)]
        return sorted(pairs, key=lambda p: p[0])

    commits = [[c["index"], c["hash"], c["date"], c["message"], c["agent"] or "",
                1 if c["is_merge"] else 0, sparse(c["lines"]), sparse(c["test_lines"]), c.get("tokens", 0)]
               for c in data["commits"]]
    embedded = {"languages": data["languages"], "commits": commits, "summary": data["summary"],
                "generated": generated}
    if locale:
        embedded["locale"] = locale
    return embedded


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
    today = datetime.now().strftime("%Y-%m-%d")
    region = detect_locale()
    json_blob = json.dumps(build_embedded(data, today, region), separators=(",", ":"))

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

    # Full commit bodies are large (over a megabyte across the history), so they
    # live in a sidecar script the page loads only when a row is first expanded.
    bodies = {c["hash"]: c["body"] for c in data["commits"] if c.get("body")}
    with open(BODIES_FILE, "w") as f:
        f.write("var COMMIT_BODIES = " + json.dumps(bodies, separators=(",", ":")) + ";\n")

    with open(HTML_FILE, "w") as f:
        f.write(html)

    size_kb = os.path.getsize(HTML_FILE) / 1024
    total = data["summary"]["total_commits"]
    first = data["summary"]["first_date"]
    last = data["summary"]["last_date"]
    print(f"Updated {HTML_FILE}")
    print(f"Wrote {BODIES_FILE} ({os.path.getsize(BODIES_FILE) / 1024:.0f} KB, {len(bodies):,} bodies)")
    print(f"  File size: {size_kb:.0f} KB")
    print(f"  Commits: {total:,}")
    print(f"  Date range: {first} to {last}")
    print(f"  Locale: {region or 'none recorded, the browser decides'}")


if __name__ == "__main__":
    main()
