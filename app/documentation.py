"""Small escaped Markdown renderer for bundled, offline product documentation."""

from __future__ import annotations

import html
import re
from pathlib import Path

from app.product import AUTHOR, VERSION

DOCUMENTS = {
    "HELP.html": ("Руководство", "docs/USAGE.md"),
    "LICENSE.html": ("Лицензия", "docs/LICENSE.ru.md"),
    "PRIVACY.html": ("Приватность", "docs/PRIVACY.md"),
    "THIRD_PARTY_NOTICES.html": ("Сторонние компоненты", "THIRD_PARTY_NOTICES.md"),
    "CHANGELOG.html": ("История изменений", "docs/CHANGELOG.md"),
}
DOC_CSS = """
:root{color-scheme:dark;font:16px/1.65 'Segoe UI',system-ui,sans-serif;background:#07111c;color:#eaf2f8}
*{box-sizing:border-box}body{max-width:920px;margin:auto;padding:28px 24px 64px}
nav{display:flex;flex-wrap:wrap;gap:12px 20px;padding-bottom:20px;border-bottom:1px solid #294259}
a{color:#22c7ff;text-underline-offset:4px;overflow-wrap:anywhere}a:focus-visible{outline:2px solid #22c7ff;outline-offset:4px}
h1{font-size:32px;line-height:1.2;margin:32px 0 20px}h2{font-size:22px;margin-top:32px}h3{font-size:18px}
p,li{overflow-wrap:anywhere}li{margin:8px 0}code{font:14px/1.6 Consolas,monospace;background:#102337;padding:2px 5px;border-radius:4px}
pre{overflow:auto;padding:18px;background:#0c1a29;border:1px solid #294259;border-radius:10px;white-space:pre-wrap;overflow-wrap:anywhere}
pre code{padding:0;background:none}table{border-collapse:collapse;display:block;overflow:auto;max-width:100%}
td,th{padding:10px 14px;text-align:left;border:1px solid #294259;vertical-align:top}
footer{margin-top:36px;border-top:1px solid #294259;padding-top:18px;color:#a0b3c4;font-size:14px}
@media(max-width:600px){body{padding:20px 16px 40px}h1{font-size:27px}}
"""


def inline(text: str) -> str:
    def link(match):
        label, address = match.groups()
        replacements = {
            "USAGE.md": "HELP.html", "LICENSE.ru.md": "LICENSE.html",
            "PRIVACY.md": "PRIVACY.html", "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.html",
            "CHANGELOG.md": "CHANGELOG.html",
        }
        address = replacements.get(address, address)
        # The renderer never passes raw HTML or executable URL schemes through.
        if not (address.startswith(("https://", "http://", "#", "licenses/")) or address in DOCUMENTS):
            return label
        external = ' target="_blank" rel="noopener noreferrer"' if address.startswith(("https://", "http://")) else ""
        return f'<a href="{address}"{external}>{label}</a>'

    value = html.escape(text, quote=True)
    value = re.sub(r"\[([^\]]+)\]\(([^\s)]+)\)", link, value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)


def render_markdown(source: str) -> str:
    output, paragraph, code = [], [], []
    in_code = in_list = in_table = False

    def flush():
        if paragraph:
            output.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    for line in [*source.splitlines(), ""]:
        if line.startswith("```"):
            flush()
            if in_code:
                output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if in_list and not line.startswith("- "):
            output.append("</ul>")
            in_list = False
        if in_table and not line.startswith("|"):
            output.append("</tbody></table>")
            in_table = False
        if not line.strip():
            flush()
        elif line.startswith("#"):
            flush()
            level = min(6, len(line) - len(line.lstrip("#")))
            output.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
        elif line.startswith("- "):
            flush()
            if not in_list:
                output.append("<ul>")
                in_list = True
            output.append("<li>" + inline(line[2:]) + "</li>")
        elif line.startswith("|"):
            flush()
            cells = line.strip("|").split("|")
            if all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
                continue
            tag = "td" if in_table else "th"
            if not in_table:
                output.append("<table><tbody>")
                in_table = True
            output.append("<tr>" + "".join(f"<{tag}>{inline(c.strip())}</{tag}>" for c in cells) + "</tr>")
        else:
            paragraph.append(line)
    if in_code:
        output.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    return "\n".join(output)


def document_source(root: Path, name: str) -> str:
    source = (root / DOCUMENTS[name][1]).read_text(encoding="utf-8").replace("{{VERSION}}", VERSION)
    if name == "LICENSE.html":
        source += "\n\n```text\n" + (root / "LICENSE").read_text(encoding="utf-8") + "\n```\n"
    return source


def render_document(name: str, source: str) -> str:
    title = DOCUMENTS[name][0]
    navigation = " ".join(f'<a href="{filename}">{label}</a>' for filename, (label, _) in DOCUMENTS.items())
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} · WorkTimer</title><link rel="stylesheet" href="docs.css"></head>'
        f'<body><nav aria-label="Документы">{navigation}</nav><main>{render_markdown(source)}</main>'
        f'<footer>WorkTimer {VERSION} · {html.escape(AUTHOR)} · Документ доступен без интернета.</footer></body></html>'
    )
