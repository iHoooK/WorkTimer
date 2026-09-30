from __future__ import annotations

import unittest

from app.documentation import render_markdown


class DocumentationTests(unittest.TestCase):
    def test_documents_escape_html_and_do_not_create_executable_links(self):
        result = render_markdown('# <script>alert(1)</script>\n\n[x](javascript:alert)\n\n```\n<a onclick="x">\n```')
        self.assertNotIn("<script>", result)
        self.assertNotIn('href="javascript:', result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("&lt;a onclick=", result)

    def test_offline_and_external_links_have_distinct_navigation(self):
        result = render_markdown("[Help](USAGE.md) [Author](https://promptix.ru/)")
        self.assertIn('href="HELP.html"', result)
        self.assertIn('rel="noopener noreferrer"', result)
