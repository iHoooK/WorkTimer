"""Per-data-directory lock, held for the whole lifetime of the process."""

from __future__ import annotations

import json
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory: str, port: int):
        self.path = Path(directory) / "instance.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.port = port
        self.acquired = False

    def acquire(self) -> bool:
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b" ")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.acquired = True
        # Byte zero stays reserved for the lock; the rest is readable metadata.
        self.file.seek(1)
        self.file.truncate()
        self.file.write(json.dumps({"port": self.port, "pid": os.getpid()}).encode())
        self.file.flush()
        return True

    def existing_port(self) -> int:
        try:
            self.file.seek(1)
            return int(json.loads(self.file.read()).get("port", self.port))
        except ValueError, OSError:
            return self.port

    def close(self):
        if self.acquired and os.name == "nt":
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()
