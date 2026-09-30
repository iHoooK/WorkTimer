"""Collect exact release licenses, a replaceable LGPL library, and offline help."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import sqlite3
import ssl
import sys
import tarfile
from pathlib import Path

from app.documentation import DOC_CSS, DOCUMENTS, document_source, render_document
from app.product import AUTHOR, COPYRIGHT, NAME, VERSION

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "2ab6bd15c14b400c9e8271a82c9de8adc0f1a0cacfc14080bdd4fb42bb88ec92"


def external_pystray(destination: Path):
    distribution = importlib.metadata.distribution("pystray")
    archive = ROOT / "licenses" / "sources" / f"pystray-{distribution.version}.tar.gz"
    if distribution.version != "0.19.5" or hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("Update and verify the exact LGPL source archive before changing pystray")
    package = Path(distribution.locate_file("pystray"))
    # Verify every shipped library source matches the supplied complete original source archive.
    with tarfile.open(archive) as source:
        for path in package.rglob("*.py"):
            member = source.extractfile(f"pystray-{distribution.version}/lib/pystray/{path.relative_to(package).as_posix()}")
            if member is None or member.read().replace(b"\r\n", b"\n") != path.read_bytes().replace(b"\r\n", b"\n"):
                raise RuntimeError(f"pystray source differs from supplied archive: {path.name}")
    shutil.copytree(package, destination / "components" / "pystray", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    source_destination = destination / "licenses" / "sources"
    source_destination.mkdir(parents=True)
    shutil.copy2(archive, source_destination / archive.name)
    return distribution


def collect_licenses(destination: Path, pystray_distribution):
    components = []
    internal = destination / "_internal"
    distributions = list(importlib.metadata.distributions(path=[str(internal)])) + [pystray_distribution]
    for distribution in sorted(distributions, key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        component_directory = destination / "licenses" / name
        texts = []
        for file in distribution.files or []:
            if not re.match(r"^(LICENSE|COPYING|NOTICE|AUTHORS)(\b|[._-])", file.name, re.IGNORECASE):
                continue
            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            component_directory.mkdir(parents=True, exist_ok=True)
            target = component_directory / file.name
            shutil.copy2(source, target)
            texts.append(target.relative_to(destination).as_posix())
        if not texts:
            raise RuntimeError(f"No full license found for bundled dependency: {name}")
        license_name = distribution.metadata.get("License-Expression") or distribution.metadata.get("License")
        if not license_name or len(license_name) > 100:
            license_name = "См. полный текст"
        components.append({"name": name, "version": distribution.version, "license": license_name, "texts": texts})
    expected = {line.split("==")[0].lower().replace("_", "-")
                for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if "==" in line}
    found = {component["name"].lower().replace("_", "-") for component in components}
    if missing := expected - found:
        raise RuntimeError(f"Release metadata/licenses missing for runtime dependencies: {sorted(missing)}")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Missing license from the exact Windows Python distribution")
    shutil.copy2(python_license, destination / "licenses" / "Python-Windows-LICENSE.txt")
    openssl_license = ROOT / "licenses" / "native" / "OpenSSL-3.5.7-LICENSE.txt"
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL 3.5.7 "):
        raise RuntimeError("Refresh the native OpenSSL notices before updating the Python runtime")
    shutil.copy2(openssl_license, destination / "licenses" / openssl_license.name)
    # Python's complete license includes native component notices and Windows redistribution conditions.
    runtime = {"python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION, "sqlite": sqlite3.sqlite_version,
               "packager": importlib.metadata.version("pyinstaller")}
    (destination / "licenses" / "COMPONENTS.json").write_text(
        json.dumps({"runtime": runtime, "packages": components}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return components, runtime


def prepare_release_documents(destination: Path):
    distribution = external_pystray(destination)
    components, runtime = collect_licenses(destination, distribution)
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE.txt")
    (destination / "docs.css").write_text(DOC_CSS, encoding="utf-8")
    for name in DOCUMENTS:
        source = document_source(ROOT, name)
        if name == "THIRD_PARTY_NOTICES.html":
            source += (
                f"\n\nPython {runtime['python']}; {runtime['openssl']}; SQLite {runtime['sqlite']}. "
                "[Полный текст Python и уведомления Windows-сборки](licenses/Python-Windows-LICENSE.txt).\n\n"
                "OpenSSL © The OpenSSL Project Authors, Apache-2.0; "
                "[полный текст](licenses/OpenSSL-3.5.7-LICENSE.txt). "
                "SQLite — public domain ([SQLite](https://www.sqlite.org/copyright.html)).\n\n"
                "| Компонент | Версия | Лицензия | Полные тексты |\n|---|---|---|---|\n"
            )
            for component in components:
                links = ", ".join(f"[{Path(p).name}]({p})" for p in component["texts"])
                source += f"| {component['name']} | {component['version']} | {component['license']} | {links} |\n"
            source += f"\n[Исходный архив pystray {distribution.version}](licenses/sources/pystray-{distribution.version}.tar.gz).\n"
        (destination / name).write_text(render_document(name, source), encoding="utf-8")
    (destination / "components" / "README.txt").write_text(
        "pystray is LGPLv3-or-later, Copyright (C) 2016-2022 Moses Palmér.\n"
        "This original Python source package is loaded directly from components/pystray.\n"
        "Close WorkTimer and replace it with an interface-compatible modified package; then restart.\n"
        "No rebuild or signature bypass is needed. Modification and reverse engineering for debugging\n"
        "such modifications are permitted. See licenses/pystray/COPYING and COPYING.LGPL,\n"
        "the complete source archive in licenses/sources, and THIRD_PARTY_NOTICES.html.\n",
        encoding="utf-8",
    )


def write_version_resource(path: Path):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version = tuple(int(p) for p in VERSION.split(".")) + (0,)
    resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3F, flags=0, OS=0x40004, fileType=1, subtype=0,
                          date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", AUTHOR), StringStruct("FileDescription", "WorkTimer — локальный таймер"),
            StringStruct("FileVersion", VERSION), StringStruct("InternalName", NAME),
            StringStruct("LegalCopyright", COPYRIGHT), StringStruct("OriginalFilename", "WorkTimer.exe"),
            StringStruct("ProductName", NAME), StringStruct("ProductVersion", VERSION),
        ])]), VarFileInfo([VarStruct("Translation", [0x0409, 1200])])],
    )
    path.write_text(str(resource), encoding="utf-8")
