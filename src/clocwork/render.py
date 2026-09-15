"""Render the dashboard: template.html plus the analysis, out to a workspace.

The template ships inside the package and carries no data. It has four
placeholders - __TITLE__, __REPO_NAME__, __ANNOTATIONS__ and __DATA__ - which
are replaced with plain str.replace, data last so that a placeholder-shaped
string inside a commit message is left alone. The header and footer figures
(commit count, date range, generation date) are not written here: the page
renders them from the blob, formatted for the region locale recorded by
detect_locale() below.
"""

import html as html_lib
import json
import os
import subprocess
import sys
from datetime import datetime
from importlib import resources

# One colour per first appearance, cycled by index. The order is the order
# the ten original hand-written annotations used, so existing pages keep their look.
PALETTE = ["#d2a8ff", "#58a6ff", "#f0883e", "#79c0ff", "#56d4dd",
           "#f778ba", "#e3b341", "#7ee787", "#ffa198", "#f2cc60"]


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
    explicit = bcp47(env.get("CLOCWORK_LOCALE"))
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


def annotations(first_appearances):
    """[[date, label, colourIndex], ...] in order of first appearance.

    Labels drop the leading "Claude " so "Claude Opus 4.6" reads "Opus 4.6",
    as the hand-written annotations did; other agents keep their name.
    """
    ordered = sorted(first_appearances.items(), key=lambda kv: kv[1]["index"])
    return [[info["date"], agent.removeprefix("Claude "), i] for i, (agent, info) in enumerate(ordered)]


def template():
    # importlib.resources, not a filesystem path: this must also work from a zipapp.
    return resources.files("clocwork").joinpath("template.html").read_text(encoding="utf-8")


def render_page(data, *, title, repo_name, generated, locale):
    page = template()
    page = page.replace("__ANNOTATIONS__", json.dumps(annotations(data.get("first_appearances", {}))))
    page = page.replace("__TITLE__", html_lib.escape(title))
    page = page.replace("__REPO_NAME__", html_lib.escape(repo_name))
    blob = json.dumps(build_embedded(data, generated, locale), separators=(",", ":"))
    return page.replace("__DATA__", blob)     # last, so data cannot contain a live placeholder


def render_workspace(workspace, *, title, repo_name, locale, log=print):
    """Write index.html and commit_bodies.js from the workspace's full_commit_data.json."""
    with open(os.path.join(workspace, "full_commit_data.json"), encoding="utf-8") as f:
        data = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    page = render_page(data, title=title, repo_name=repo_name, generated=today, locale=locale)
    # Full commit bodies are large (over a megabyte across a long history), so
    # they live in a sidecar script the page loads only when a row is expanded.
    bodies = {c["hash"]: c["body"] for c in data["commits"] if c.get("body")}
    bodies_path = os.path.join(workspace, "commit_bodies.js")
    with open(bodies_path, "w", encoding="utf-8") as f:
        f.write("var COMMIT_BODIES = " + json.dumps(bodies, separators=(",", ":")) + ";\n")
    html_path = os.path.join(workspace, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    s = data["summary"]
    log(f"Wrote {html_path} ({os.path.getsize(html_path) / 1024:.0f} KB) "
        f"and commit_bodies.js ({os.path.getsize(bodies_path) / 1024:.0f} KB, {len(bodies):,} bodies)")
    log(f"  Commits: {s['total_commits']:,}, {s['first_date']} to {s['last_date']}")
    log(f"  Locale: {locale or 'none recorded, the browser decides'}")
    return html_path
