"""Prepare installer, portable ZIP and checksums for a GitHub release, without uploading."""

from __future__ import annotations

import hashlib
import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.documentation import DOC_CSS, render_markdown  # noqa: E402
from app.product import VERSION  # noqa: E402
from scripts.build import BUILD, INSTALLER_NAME, PORTABLE_NAME  # noqa: E402

RELEASE = ROOT / "Release"


def release_notes() -> str:
    changelog = (ROOT / "docs/CHANGELOG.md").read_text(encoding="utf-8")
    section = re.search(rf"^## {re.escape(VERSION)}(?:\s[^\n]*)?\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if not section or not section[1].strip():
        raise RuntimeError(f"Добавьте описание версии {VERSION} в docs/CHANGELOG.md")
    template = (ROOT / "docs/RELEASE_NOTES_TEMPLATE.md").read_text(encoding="utf-8")
    return template.replace("{{VERSION}}", VERSION).replace("{{CHANGES}}", section[1].strip())


def write_guide(destination: Path, notes: str):
    source = (ROOT / "docs/GITHUB_RELEASE_GUIDE_TEMPLATE.md").read_text(encoding="utf-8")
    guide = source.replace("{{VERSION}}", VERSION)
    (ROOT / "docs/GITHUB_RELEASE_GUIDE.md").write_text(guide, encoding="utf-8")
    (destination / "GUIDE.md").write_text(guide, encoding="utf-8")
    (destination / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")
    script = """
for(const pre of document.querySelectorAll('pre')){const button=document.createElement('button');button.type='button';button.textContent='Копировать';button.dataset.copy='code';pre.append(button);}
const status=document.querySelector('#copy-status');
for(const button of document.querySelectorAll('[data-copy]'))button.addEventListener('click',async()=>{
  const text=button.dataset.copy==='notes'?document.querySelector('#release-notes').value:button.parentElement.querySelector('code').textContent;
  try{await navigator.clipboard.writeText(text);status.textContent='Скопировано';}
  catch{const field=document.querySelector('#manual-copy');field.hidden=false;field.value=text;field.focus();field.select();status.textContent='Нажмите Ctrl+C, чтобы скопировать выделенный текст';}
});
"""
    style = DOC_CSS + """
body{max-width:1040px}nav{position:sticky;top:0;background:#07111cf2;padding:14px 0;z-index:1}
.hero{padding:24px 0}.hero strong{color:#22c7ff}.tools{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
button,.tools a{font:inherit;background:#102337;color:#eaf2f8;border:1px solid #294259;border-radius:8px;padding:9px 14px;cursor:pointer;text-decoration:none}
button:hover,.tools a:hover{border-color:#22c7ff}button:focus-visible{outline:2px solid #22c7ff;outline-offset:3px}
pre button{display:block;margin-top:12px;font-size:13px}textarea{width:100%;min-height:200px;background:#0c1a29;color:#eaf2f8;border:1px solid #294259;padding:16px;font:14px/1.6 Consolas,monospace}
.callout{padding:16px 20px;border:1px solid #30687b;border-radius:10px;background:#0e2e3b}
details{margin:24px 0}summary{cursor:pointer;padding:12px 0}#copy-status{min-height:26px;color:#22c7ff}
@media print{nav,button,.tools,#copy-status,#manual-copy{display:none}body{background:white;color:black;max-width:none}a{color:black}pre,code,.callout,textarea{background:white;color:black}}
"""
    page = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Публикация WorkTimer {VERSION} · Пошаговый гид</title><style>{style}</style></head><body>'
        '<nav aria-label="Навигация"><a href="#guide">Инструкция</a><a href="#notes">Текст релиза</a>'
        '<a href="https://github.com/iHoooK/WorkTimer/releases/new" target="_blank" rel="noopener noreferrer">Создать релиз на GitHub ↗</a></nav>'
        f'<header class="hero"><strong>Готовый комплект · WorkTimer {VERSION}</strong>'
        '<p>Два варианта программы и файл контрольных сумм. Загружайте файлы из папки <code>Uploads</code>; '
        'этот гид остаётся у вас.</p><div class="tools">'
        f'<a href="Uploads/WorkTimer-Setup-{VERSION}.exe">Установщик EXE</a>'
        f'<a href="Uploads/WorkTimer-Portable-{VERSION}.zip">Portable ZIP</a>'
        '<a href="Uploads/SHA256SUMS">SHA256SUMS</a></div></header>'
        '<aside class="callout">Перед публикацией отправьте актуальный код и README в main. '
        'В форме релиза используйте ту же версию, что и в именах файлов.</aside>'
        '<main id="guide">' + render_markdown(guide) + '</main>'
        '<section id="notes"><h2>Готовый текст описания релиза</h2>'
        '<button type="button" data-copy="notes">Скопировать описание для GitHub</button>'
        '<p id="copy-status" role="status" aria-live="polite"></p>'
        '<textarea id="manual-copy" aria-label="Текст для ручного копирования" readonly hidden></textarea>'
        '<details><summary>Открыть Markdown для копирования</summary>'
        f'<textarea id="release-notes" aria-label="Описание релиза в Markdown" readonly>{html.escape(notes)}</textarea></details>'
        '<details><summary>Посмотреть оформление описания</summary>' + render_markdown(notes) + '</details></section>'
        f'<footer>WorkTimer {VERSION} · Гид работает без интернета. Ссылки GitHub открываются по нажатию.</footer>'
        f'<script>{script}</script></body></html>'
    )
    (destination / "GUIDE.html").write_text(page, encoding="utf-8")


def prepare_assets() -> Path:
    output = RELEASE / "Uploads"
    if RELEASE.resolve().parent != ROOT.resolve() or RELEASE.is_symlink() or output.is_symlink():
        raise ValueError("Unsafe release output directory")
    if output.resolve() != ROOT.resolve() / "Release" / "Uploads":
        raise ValueError("Release uploads must stay inside the workspace")
    installer = BUILD / INSTALLER_NAME
    portable = BUILD / PORTABLE_NAME
    if not installer.is_file() or not (portable / "WorkTimer.exe").is_file():
        raise RuntimeError("Сначала соберите релиз: bash scripts/build.sh")
    notes = release_notes()
    output.mkdir(parents=True, exist_ok=True)
    # Only remove known files directly inside the validated generated uploads directory.
    for path in output.iterdir():
        if path.is_file() and (re.fullmatch(r"WorkTimer-(Setup|Portable)-\d+\.\d+\.\d+\.(exe|zip)", path.name)
                               or path.name == "SHA256SUMS"):
            path.unlink()
    copied = output / INSTALLER_NAME
    shutil.copy2(installer, copied)
    archive = Path(shutil.make_archive(str(output / f"WorkTimer-Portable-{VERSION}"), "zip", BUILD, PORTABLE_NAME))
    lines = []
    for path in (copied, archive):
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}\n")
    (output / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    write_guide(RELEASE, notes)
    print(f"Файлы для GitHub Release v{VERSION}: {output}")
    return output


if __name__ == "__main__":
    prepare_assets()
