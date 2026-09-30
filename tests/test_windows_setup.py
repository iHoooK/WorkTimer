from __future__ import annotations

import ctypes
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from infrastructure.windows_setup import ShellExecuteInfo, launch_installer


class WindowsSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.shell = Mock()
        self.kernel = Mock()
        self.kernel.WaitForSingleObject.return_value = 0
        self.arguments = [str(self.folder / "setup.exe"), "/WORKTIMERHANDOFF=1", "/DIR=C:\\Program Files\\WorkTimer"]

    def tearDown(self):
        self.temp.cleanup()

    def launch(self):
        with patch("ctypes.WinDLL", side_effect=[self.shell, self.kernel]):
            launch_installer(self.arguments, cwd=self.folder, cancelled=threading.Event())

    def started(self, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(ShellExecuteInfo)).contents
        info.hProcess = 123
        self.assertEqual(info.lpVerb, "open")
        self.assertIn('"/DIR=C:\\Program Files\\WorkTimer"', info.lpParameters)
        return True

    def test_denied_elevation_returns_error_without_waiting(self):
        self.shell.ShellExecuteExW.return_value = False
        with patch("ctypes.get_last_error", return_value=1223), self.assertRaisesRegex(ValueError, "отменена"):
            self.launch()
        self.kernel.WaitForSingleObject.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_exit_before_handoff_is_error_and_closes_handle(self):
        self.shell.ShellExecuteExW.side_effect = self.started
        with self.assertRaisesRegex(ValueError, "закрыт"):
            self.launch()
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_fresh_handoff_succeeds_and_closes_handle(self):
        def acknowledge(pointer):
            self.started(pointer)
            (self.folder / "update-ready").write_text("ready")
            return True

        self.shell.ShellExecuteExW.side_effect = acknowledge
        self.launch()
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_stale_handoff_is_removed_before_launch(self):
        (self.folder / "update-ready").write_text("stale")
        self.shell.ShellExecuteExW.side_effect = self.started
        with self.assertRaisesRegex(ValueError, "закрыт"):
            self.launch()
        self.assertFalse((self.folder / "update-ready").exists())


if __name__ == "__main__":
    unittest.main()
