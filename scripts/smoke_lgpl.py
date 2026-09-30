"""Verify the frozen app loads a modified external LGPL library without rebuilding."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    args = parser.parse_args()
    exe = Path(args.exe).resolve()
    reader = CArchiveReader(str(exe))
    archive_name = next(name for name in reader.toc if name.endswith(".pyz"))
    embedded = reader.open_embedded_archive(archive_name)
    assert not any(name == "pystray" or name.startswith("pystray.") for name in embedded.toc)
    smoke_root = ROOT / ".build-work" / "smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lgpl-", dir=smoke_root) as temp:
        directory = Path(temp)
        copied = directory / "Program"
        shutil.copytree(exe.parent, copied)
        library = copied / "components" / "pystray" / "__init__.py"
        library.write_text(library.read_text(encoding="utf-8") +
                           '\nimport logging\nlogging.getLogger(__name__).info("LGPL replacement check loaded")\n',
                           encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run([str(copied / exe.name), "--data-dir", str(directory / "Data"), "--port", str(port),
                        "--no-browser", "--no-hotkeys", "--exit-after", "1.5"], check=True, timeout=25,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        log = (directory / "Data" / "worktimer.log").read_text(encoding="utf-8")
        assert "LGPL replacement check loaded" in log
        assert "TrayManager: иконка создана" in log
        assert "Traceback" not in log and "[ERROR]" not in log
    print(json.dumps({"passed": True, "pystray_not_frozen": True, "modified_external_library_loaded": True,
                      "tray_started_with_modified_library": True}))


if __name__ == "__main__":
    main()
