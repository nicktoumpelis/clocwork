import unittest

import generate_html as gh

DATA = {
    "languages": ["Swift", "Markdown"],
    "commits": [
        {"index": 0, "hash": "abc1234", "date": "2025-01-01", "message": "Initial", "agent": None, "is_merge": False,
         "lines": {"Markdown": [2, 0, 0, 0, 1, 0], "Swift": [3, 0, 2, 0, 1, 0]}, "test_lines": {}},
        {"index": 1, "hash": "def5678", "date": "2025-01-04", "message": "Merge pull request #1", "agent": "Misc",
         "is_merge": True, "lines": {}, "test_lines": {}},
    ],
    "summary": {"total_commits": 2},
}


class TestBuildEmbedded(unittest.TestCase):
    def test_compact_rows(self):
        e = gh.build_embedded(DATA)
        self.assertEqual(e["languages"], ["Swift", "Markdown"])
        self.assertEqual(e["commits"][0], [0, "abc1234", "2025-01-01", "Initial", "", 0,
                                           [[0, [3, 0, 2, 0, 1, 0]], [1, [2, 0, 0, 0, 1, 0]]], []])
        self.assertEqual(e["commits"][1], [1, "def5678", "2025-01-04", "Merge pull request #1", "Misc", 1, [], []])
        self.assertEqual(e["summary"], {"total_commits": 2})
        self.assertNotIn("daily", e)
        self.assertNotIn("agentStats", e)


class TestReplaceDataLine(unittest.TestCase):
    def test_replaces_whole_line_even_with_embedded_marker(self):
        # The old blob contains a literal '};' inside a JSON string value, which
        # broke the previous marker_start/marker_end/index-based replacement.
        html = (
            "before line 1\n"
            "before line 2\n"
            'var RAW = {"languages":[],"commits":[[0,"abc","2025-01-01","subject with }; inside",""]]};\n'
            "after line 1\n"
            "after line 2\n"
        )
        new_blob = '{"languages":["Swift"],"commits":[]}'
        result = gh.replace_data_line(html, new_blob)
        self.assertEqual(
            result,
            "before line 1\n"
            "before line 2\n"
            f"var RAW = {new_blob};\n"
            "after line 1\n"
            "after line 2\n",
        )

    def test_missing_line_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            gh.replace_data_line("no data line here at all\n", "{}")
