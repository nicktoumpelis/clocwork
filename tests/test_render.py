import json
import os
import re
import tempfile
import unittest
from unittest import mock

from clocwork import render as gh

DATA = {
    "languages": ["Swift", "Markdown"],
    "commits": [
        {"index": 0, "hash": "abc1234", "date": "2025-01-01", "message": "Initial", "agent": None, "is_merge": False,
         "lines": {"Markdown": [2, 0, 0, 0, 1, 0], "Swift": [3, 0, 2, 0, 1, 0]}, "test_lines": {}, "tokens": 1234, "token_kind": "e"},
        {"index": 1, "hash": "def5678", "date": "2025-01-04", "message": "Merge pull request #1", "agent": "Misc",
         "is_merge": True, "lines": {}, "test_lines": {}},
    ],
    "summary": {"total_commits": 2},
}


class TestBuildEmbedded(unittest.TestCase):
    def test_compact_rows(self):
        e = gh.build_embedded(DATA, generated="2026-09-07", locale="en-SE")
        self.assertEqual(e["languages"], ["Swift", "Markdown"])
        self.assertEqual(e["commits"][0], [0, "abc1234", "2025-01-01", "Initial", "", 0,
                                           [[0, [3, 0, 2, 0, 1, 0]], [1, [2, 0, 0, 0, 1, 0]]], [], 1234, "e"])
        # Data written before tokens were attributed per commit has neither key: zero and no kind.
        self.assertEqual(e["commits"][1], [1, "def5678", "2025-01-04", "Merge pull request #1", "Misc", 1, [], [], 0, ""])
        self.assertEqual(e["summary"], {"total_commits": 2})
        self.assertNotIn("daily", e)
        self.assertNotIn("agentStats", e)

    def test_embeds_generation_date_for_the_page_to_format(self):
        # The page formats this itself, so it must travel as ISO.
        e = gh.build_embedded(DATA, generated="2026-09-07", locale="en-SE")
        self.assertEqual(e["generated"], "2026-09-07")

    def test_embeds_region_locale_for_the_page_to_format_with(self):
        e = gh.build_embedded(DATA, generated="2026-09-07", locale="en-SE")
        self.assertEqual(e["locale"], "en-SE")

    def test_embeds_the_build_that_rendered_the_page(self):
        build = {"version": "9.9.9", "commit": "abc1234"}
        e = gh.build_embedded(DATA, generated="2026-09-07", locale=None, rendered_by=build)
        self.assertEqual(e["rendered_by"], build)

    def test_omits_the_build_when_none_given(self):
        self.assertNotIn("rendered_by", gh.build_embedded(DATA, generated="2026-09-07", locale=None))

    def test_omits_locale_when_none_detected(self):
        e = gh.build_embedded(DATA, generated="2026-09-07", locale=None)
        self.assertNotIn("locale", e)


class TestRegionLocale(unittest.TestCase):
    """Browsers expose only the language list, never the OS region, so the
    generator records the machine's region locale for the page to format with."""

    def test_bcp47_normalises_posix_and_apple_tags(self):
        self.assertEqual(gh.bcp47("en_SE"), "en-SE")
        self.assertEqual(gh.bcp47("de_DE.UTF-8"), "de-DE")
        self.assertEqual(gh.bcp47(" sv-SE\n"), "sv-SE")

    def test_bcp47_rejects_non_locales(self):
        for tag in ("", None, "C", "POSIX", "C.UTF-8"):
            self.assertIsNone(gh.bcp47(tag), tag)

    def test_bcp47_carries_icu_keywords_as_unicode_extensions(self):
        # macOS appends per-setting customisations as ICU keywords; Intl
        # understands the same settings only in BCP 47 -u- form.
        self.assertEqual(gh.bcp47("en_SE@calendar=japanese"), "en-SE-u-ca-japanese")
        self.assertEqual(gh.bcp47("en_US@ms=metric;numbers=arab"), "en-US-u-ms-metric-nu-arab")
        self.assertEqual(gh.bcp47("en_US@calendar=gregorian"), "en-US-u-ca-gregory")
        self.assertEqual(gh.bcp47("en_SE@rg=gbzzzz"), "en-SE-u-rg-gbzzzz")
        self.assertEqual(gh.bcp47("en_US@mystery=x"), "en-US")

    @staticmethod
    def apple(**settings):
        return lambda key: settings.get(key, "")

    def test_explicit_override_wins(self):
        env = {"CLOCWORK_LOCALE": "el_GR", "LANG": "en_US.UTF-8"}
        self.assertEqual(gh.detect_locale(env, platform="darwin", apple=self.apple(AppleLocale="en_SE")), "el-GR")

    def test_macos_region_setting_beats_the_shell_locale(self):
        env = {"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
        self.assertEqual(gh.detect_locale(env, platform="darwin", apple=self.apple(AppleLocale="en_SE")), "en-SE")

    def test_macos_measurement_setting_becomes_a_ms_extension(self):
        # System Settings > Language & Region > Measurement system, stored as a
        # boolean; absent means the region's own default applies.
        self.assertEqual(gh.detect_locale({}, "darwin", self.apple(AppleLocale="en_SE", AppleMetricUnits="0")), "en-SE-u-ms-ussystem")
        self.assertEqual(gh.detect_locale({}, "darwin", self.apple(AppleLocale="en_US", AppleMetricUnits="1")), "en-US-u-ms-metric")
        self.assertEqual(gh.detect_locale({}, "darwin", self.apple(AppleLocale="en_SE")), "en-SE")
        # An explicit setting wins over a keyword already in the locale.
        self.assertEqual(gh.detect_locale({}, "darwin", self.apple(AppleLocale="en_SE@ms=ussystem", AppleMetricUnits="1")), "en-SE-u-ms-metric")

    def test_posix_variables_in_precedence_order_elsewhere(self):
        env = {"LANG": "en_US.UTF-8", "LC_ALL": "de_DE.UTF-8"}
        self.assertEqual(gh.detect_locale(env, platform="linux", apple=self.apple(AppleLocale="en_SE")), "de-DE")
        self.assertEqual(gh.detect_locale({"LANG": "fr_FR.UTF-8"}, platform="linux", apple=self.apple()), "fr-FR")

    def test_nothing_detected_gives_none(self):
        self.assertIsNone(gh.detect_locale({"LANG": "C.UTF-8"}, platform="linux", apple=self.apple()))
        self.assertIsNone(gh.detect_locale({}, platform="darwin", apple=self.apple()))


class TestAnnotations(unittest.TestCase):
    def test_from_first_appearances_in_index_order(self):
        fa = {"Claude Opus 4.6": {"date": "2026-02-05", "index": 9}, "Copilot": {"date": "2026-01-01", "index": 2}}
        self.assertEqual(gh.annotations(fa), [["2026-01-01", "Copilot", 0], ["2026-02-05", "Opus 4.6", 1]])

    def test_same_day_appearances_share_a_line(self):
        fa = {"Claude Opus 4.6 (1M)": {"date": "2026-03-14", "index": 5}, "Claude Sonnet 4.6": {"date": "2026-03-14", "index": 7},
              "Copilot": {"date": "2026-04-01", "index": 9}}
        self.assertEqual(gh.annotations(fa), [["2026-03-14", "Opus 4.6 (1M) + Sonnet 4.6", 0], ["2026-04-01", "Copilot", 1]])

    def test_empty(self):
        self.assertEqual(gh.annotations({}), [])

    def test_palette_has_ten_entries_matching_the_page(self):
        self.assertEqual(len(gh.PALETTE), 10)
        self.assertIn("'" + "', '".join(gh.PALETTE) + "'", gh.template())


def full_data(**overrides):
    data = json.loads(json.dumps(DATA))
    data.setdefault("first_appearances", {})
    data.update(overrides)
    return data


class TestAgentLabels(unittest.TestCase):
    """The page keys colours and filters on the labels the analysis writes,
    so each has to be spelled the same on both sides. Python has a constant
    for two of them; the page spells all three once, and these tie the two
    together, so a rename on one side alone fails here instead of drawing
    that series in a stray colour."""

    def page_label(self, name):
        # Exactly one declaration: a second, later one is the value the page
        # would use, and the first would no longer tell.
        found = re.findall(r"^var " + name + r" = '([^']*)';", gh.template(), re.M)
        self.assertEqual(len(found), 1, name + " should be declared once in the page: " + repr(found))
        return found[0]

    def test_the_page_names_merges_as_the_analysis_does(self):
        from clocwork import analyse
        self.assertEqual(self.page_label("MISC"), analyse.MISC)

    def test_the_page_names_an_unknown_claude_as_the_matcher_does(self):
        from clocwork import agents
        self.assertEqual(self.page_label("UNKNOWN_CLAUDE"), agents.UNKNOWN_CLAUDE)

    def test_each_label_is_spelled_once_in_the_page(self):
        # A second spelling is a copy a rename would leave behind. "Human" is
        # the page's own word for a commit whose agent is null.
        t = gh.template()
        for name in ("HUMAN", "MISC", "UNKNOWN_CLAUDE"):
            label = self.page_label(name)
            with self.subTest(label=label):
                copies = t.count("'" + label + "'") + t.count('"' + label + '"')
                self.assertEqual(copies, 1, label + " is spelled more than once")

    def test_the_labels_that_are_no_agent_are_grey(self):
        t = gh.template()
        for name in ("HUMAN", "MISC", "UNKNOWN_CLAUDE"):
            with self.subTest(name=name):
                # Every assignment, not the first: a later one would win.
                found = re.findall(r"AGENT_COLORS\[" + name + r"\]\s*=\s*['\"]([a-z0-9-]+)['\"]", t)
                self.assertEqual(len(found), 1, name + " should be given one colour: " + repr(found))
                self.assertTrue(found[0].startswith("grey"), name + " is " + found[0])

    def test_every_fixed_colour_is_for_a_name_clocwork_reports(self):
        # A vendor renamed in agents.py would otherwise leave its colour on a
        # name nothing produces, and take a hashed one instead.
        from clocwork import agents
        block = re.search(r"^var AGENT_COLORS = \{(.*?)^\};", gh.template(), re.M | re.S).group(1)
        code = re.sub(r"//[^\n]*", "", block)
        keys = re.findall(r"""['"]([^'"]+)['"]\s*:""", code)
        # Every entry has one colon; a key the pattern missed would show here.
        self.assertEqual(len(keys), code.count(":"))
        self.assertGreater(len(keys), 10)
        vendors = {name for _, name in agents.VENDORS}
        for key in keys:
            with self.subTest(key=key):
                trailer = "Co-Authored-By: " + key.replace("(1M)", "(1M context)") + " <noreply@anthropic.com>"
                self.assertTrue(key in vendors or agents.parse_claude_model(trailer) == key,
                                key + " is not a name agents.py produces")


    def test_every_source_has_a_fixed_colour_of_its_own(self):
        # A source left to the palette takes its hue from its place in the
        # chart's list, so it changes colour whenever another source gains or
        # loses logs. Both directions: a new source cannot ship without a
        # colour, and a colour cannot outlive the source it was for.
        from clocwork import sources
        block = re.search(r"var SOURCE_COLOURS = \{(.*?)\};", gh.template(), re.S).group(1)
        pairs = dict(re.findall(r"""['"]([^'"]+)['"]\s*:\s*['"]([^'"]+)['"]""", block))
        self.assertEqual(len(pairs), block.count(":"))
        self.assertEqual(set(pairs), {s.KEY for s in sources.SOURCES})
        # Stacked together, two sources in one hue would read as one.
        self.assertEqual(len(set(pairs.values())), len(pairs), pairs)
        # The greys are Human, Misc and the unknown Claude on the other charts.
        self.assertFalse([c for c in pairs.values() if c.startswith("grey")], pairs)


class TestRenderPage(unittest.TestCase):
    PLACEHOLDERS = ("__TITLE__", "__REPO_NAME__", "__DATA__", "__ANNOTATIONS__")

    def test_template_carries_the_placeholders_and_no_data(self):
        t = gh.template()
        for p in self.PLACEHOLDERS:
            self.assertEqual(t.count(p), 1, p)
        self.assertNotIn("MyApp", t)
        # The dashboard harness makes any element a script asks for, so only
        # this check proves the footer has somewhere to name the build.
        self.assertEqual(t.count('<span id="generatedBy"></span>'), 1)

    def test_no_placeholder_survives_and_data_is_replaced_last(self):
        data = full_data()
        data["commits"][0]["message"] = "mentions __TITLE__ literally"
        html = gh.render_page(data, title="T & co", repo_name="R", generated="2026-09-15", locale=None)
        stripped = html.replace("mentions __TITLE__ literally", "")
        for p in self.PLACEHOLDERS:
            self.assertNotIn(p, stripped, p)
        self.assertIn("<title>T &amp; co</title>", html)
        self.assertIn("<h1><span>R</span>", html)
        self.assertIn("mentions __TITLE__ literally", html)
        self.assertRegex(html, r"(?m)^var ANNOTATIONS = \[\];")
        self.assertRegex(html, r"(?m)^var RAW = \{.*\};$")

    def test_annotations_embedded(self):
        data = full_data(first_appearances={"Claude Opus 4.6": {"date": "2025-01-02", "index": 1}})
        html = gh.render_page(data, title="T", repo_name="R", generated="2026-09-15", locale="en-SE")
        self.assertIn('var ANNOTATIONS = [["2025-01-02", "Opus 4.6", 0]];', html)


class TestRenderWorkspace(unittest.TestCase):
    def test_writes_page_and_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            data = full_data()
            data["commits"][0]["body"] = "long body"
            data["summary"].update({"first_date": "2025-01-01", "last_date": "2025-01-04"})
            with open(os.path.join(d, "full_commit_data.json"), "w") as f:
                json.dump(data, f)
            lines = []
            out = gh.render_workspace(d, title="T", repo_name="R", locale=None, log=lines.append)
            self.assertEqual(out, os.path.join(d, "index.html"))
            with open(out) as f:
                self.assertIn("var RAW = {", f.read())
            with open(os.path.join(d, "commit_bodies.js")) as f:
                self.assertEqual(f.read(), 'var COMMIT_BODIES = {"abc1234":"long body"};\n')
            self.assertTrue(any("1 bodies" in l for l in lines))

    def test_the_page_names_the_build_that_rendered_it(self):
        with tempfile.TemporaryDirectory() as d:
            data = full_data()
            data["summary"].update({"first_date": "2025-01-01", "last_date": "2025-01-04"})
            with open(os.path.join(d, "full_commit_data.json"), "w") as f:
                json.dump(data, f)
            build = {"version": "9.9.9", "commit": None}
            with mock.patch.object(gh.paths, "build", return_value=build):
                gh.render_workspace(d, title="T", repo_name="R", locale=None, log=lambda *a: None)
            with open(os.path.join(d, "index.html")) as f:
                raw = json.loads(re.search(r"(?m)^var RAW = (.*);$", f.read()).group(1))
            self.assertEqual(raw["rendered_by"], build)


if __name__ == "__main__":
    unittest.main()
