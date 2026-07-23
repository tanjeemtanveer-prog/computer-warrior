"""Windows named-mutex single-instance protection."""

from __future__ import annotations

import ctypes
import sys

from .config import ERROR_ALREADY_EXISTS


class AlreadyRunningError(RuntimeError):
    pass


class WindowsSingleInstance:
    def __init__(self, mutex_name: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows single-instance mutex requires Windows")

        from ctypes import wintypes

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        self._handle = self._kernel32.CreateMutexW(None, False, mutex_name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())

        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            self.close()
            raise AlreadyRunningError("Computer Warrior is already running")

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None

    def __enter__(self) -> "WindowsSingleInstance":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
