import json
import os
import tempfile
import unittest

from clocwork import render as gh

DATA = {
    "languages": ["Swift", "Markdown"],
    "commits": [
        {"index": 0, "hash": "abc1234", "date": "2025-01-01", "message": "Initial", "agent": None, "is_merge": False,
         "lines": {"Markdown": [2, 0, 0, 0, 1, 0], "Swift": [3, 0, 2, 0, 1, 0]}, "test_lines": {}, "tokens": 1234},
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
                                           [[0, [3, 0, 2, 0, 1, 0]], [1, [2, 0, 0, 0, 1, 0]]], [], 1234])
        # Data written before tokens were attributed per commit has no key: zero.
        self.assertEqual(e["commits"][1], [1, "def5678", "2025-01-04", "Merge pull request #1", "Misc", 1, [], [], 0])
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


class TestRenderPage(unittest.TestCase):
    PLACEHOLDERS = ("__TITLE__", "__REPO_NAME__", "__DATA__", "__ANNOTATIONS__")

    def test_template_carries_the_placeholders_and_no_data(self):
        t = gh.template()
        for p in self.PLACEHOLDERS:
            self.assertEqual(t.count(p), 1, p)
        self.assertNotIn("MyApp", t)

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


if __name__ == "__main__":
    unittest.main()
