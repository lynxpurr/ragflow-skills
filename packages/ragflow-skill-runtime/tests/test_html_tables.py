from __future__ import annotations

import unittest

from ragflow_skill_runtime import html_tables


class HtmlTableAnalysisTests(unittest.TestCase):
    def test_analysis_reports_balanced_ranges_and_fenced_lines(self) -> None:
        text = (
            "```html\n<table><tr><td>literal</td></tr></table>\n```\n"
            "<TABLE data-note=\">\"><tr><td>A</td></tr></TABLE>\n"
            "<table/>\n"
        )

        analysis = html_tables.analyze_html_table_structure(text)

        self.assertTrue(analysis.balanced)
        self.assertEqual(analysis.unclosed_table_count, 0)
        self.assertEqual(analysis.unexpected_close_count, 0)
        self.assertEqual(analysis.fenced_line_numbers, (1, 2, 3))
        self.assertEqual(
            [(item.line_start, item.line_end) for item in analysis.tables],
            [(4, 4), (5, 5)],
        )

    def test_analysis_reports_unclosed_and_unexpected_close_tags(self) -> None:
        analysis = html_tables.analyze_html_table_structure(
            "</table>\n<table><tr><td>open\n"
        )

        self.assertFalse(analysis.balanced)
        self.assertEqual(analysis.unclosed_table_count, 1)
        self.assertEqual(analysis.unexpected_close_count, 1)
