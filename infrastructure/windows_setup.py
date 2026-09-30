"""Launch Inno Setup through Windows and wait for its post-UAC handoff."""

from __future__ import annotations

import ctypes
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def launch_installer(arguments: list[str], *, cwd: Path, cancelled: threading.Event):
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ready = cwd / "update-ready"
    ready.unlink(missing_ok=True)
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    # Inno's own elevation flow retains the pre-UAC identity for runasoriginaluser.
    info.lpVerb = "open"
    info.lpFile = arguments[0]
    info.lpParameters = subprocess.list2cmdline(arguments[1:])
    info.lpDirectory = str(cwd)
    info.nShow = 1
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise ValueError("Установка отменена в запросе Windows. WorkTimer продолжает работать")
        raise ctypes.WinError(error)
    if not info.hProcess:
        raise ValueError("Не удалось дождаться установщика. Повторите обновление")
    try:
        deadline = time.monotonic() + 180
        while not cancelled.is_set():
            if ready.is_file():
                return
            if kernel.WaitForSingleObject(info.hProcess, 0) == 0:
                raise ValueError("Установщик закрыт или запрос прав отменён. WorkTimer продолжает работать")
            if time.monotonic() >= deadline:
                raise ValueError("Установщик не подтвердил запуск. Повторите обновление")
            cancelled.wait(0.1)
        raise ValueError("Установка отменена: WorkTimer завершает работу")
    finally:
        kernel.CloseHandle(info.hProcess)
