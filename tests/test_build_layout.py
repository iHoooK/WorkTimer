from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build


class BuildLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "Build"
        self.work = self.root / ".build-work"
        self.staging = self.work / "release"
        self.staging.mkdir(parents=True)
        self.patches = [patch.object(build, "ROOT", self.root), patch.object(build, "BUILD", self.output)]
        self.patches.append(patch.object(build, "WORK", self.work))
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def staged_release(self):
        portable = self.staging / build.PORTABLE_NAME
        portable.mkdir()
        (portable / "WorkTimer.exe").write_bytes(b"portable")
        (portable / "_internal").mkdir()
        (portable / "_internal" / "runtime.dll").write_bytes(b"runtime")
        (self.staging / build.INSTALLER_NAME).write_bytes(b"installer")

    def test_release_contains_only_installer_and_direct_portable_folder(self):
        self.output.mkdir()
        (self.output / "old.zip").write_bytes(b"obsolete")
        (self.output / "smoke").mkdir()
        (self.output / "smoke" / "test.db").write_bytes(b"test")
        self.staged_release()
        build.publish_release(self.staging)
        self.assertEqual({p.name for p in self.output.iterdir()}, {build.PORTABLE_NAME, build.INSTALLER_NAME})
        self.assertEqual((self.output / build.PORTABLE_NAME / "WorkTimer.exe").read_bytes(), b"portable")
        self.assertTrue((self.output / build.PORTABLE_NAME / "_internal" / "runtime.dll").is_file())

    def test_invalid_staging_preserves_previous_release(self):
        self.output.mkdir()
        (self.output / "previous.exe").write_bytes(b"keep")
        self.staged_release()
        (self.staging / "unexpected.log").write_text("extra", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            build.publish_release(self.staging)
        self.assertEqual((self.output / "previous.exe").read_bytes(), b"keep")

    def test_cleanup_rejects_parent_and_outside_paths(self):
        with self.assertRaises(ValueError):
            build.owned_path(self.output, self.output)
        with self.assertRaises(ValueError):
            build.owned_path(self.root / "review-assets", self.output)


if __name__ == "__main__":
    unittest.main()
