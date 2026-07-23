"""Windows Credential Manager storage for local Computer Warrior session tokens."""

from __future__ import annotations

import sys
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """Credential storage could not safely read, write, or delete a token."""


class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...

    def write(self, target: str, token: str) -> None: ...

    def delete(self, target: str) -> None: ...


class EphemeralCredentialStore:
    """Non-Windows test fallback. Tokens are memory-only and never serialized."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self._values.get(target)

    def write(self, target: str, token: str) -> None:
        self._values[target] = token

    def delete(self, target: str) -> None:
        self._values.pop(target, None)


class WindowsCredentialStore:
    """Stores Generic Credentials encrypted by the current Windows user profile."""

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _MAX_BLOB_BYTES = 512

    @staticmethod
    def _api():
        if sys.platform != "win32":
            raise CredentialStoreError("Windows Credential Manager is unavailable on this platform")

        import ctypes
        from ctypes import wintypes

        byte_pointer = ctypes.POINTER(wintypes.BYTE)

        class CredentialAttributeW(ctypes.Structure):
            _fields_ = [
                ("Keyword", wintypes.LPWSTR),
                ("Flags", wintypes.DWORD),
                ("ValueSize", wintypes.DWORD),
                ("Value", byte_pointer),
            ]

        class CredentialW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", byte_pointer),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.POINTER(CredentialAttributeW)),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        credential_pointer = ctypes.POINTER(CredentialW)
        advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        advapi.CredWriteW.argtypes = [credential_pointer, wintypes.DWORD]
        advapi.CredWriteW.restype = wintypes.BOOL
        advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(credential_pointer)]
        advapi.CredReadW.restype = wintypes.BOOL
        advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi.CredDeleteW.restype = wintypes.BOOL
        advapi.CredFree.argtypes = [credential_pointer]
        advapi.CredFree.restype = None
        return ctypes, wintypes, CredentialW, credential_pointer, advapi

    def read(self, target: str) -> str | None:
        ctypes, _, _, credential_pointer, advapi = self._api()
        credential = credential_pointer()
        if not advapi.CredReadW(target, self._CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
            error = ctypes.get_last_error()
            if error == self._ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError(f"Windows Credential Manager read failed ({error})")
        try:
            raw = ctypes.string_at(credential.contents.CredentialBlob, credential.contents.CredentialBlobSize)
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CredentialStoreError("Windows Credential Manager returned an invalid session token") from exc
        finally:
            advapi.CredFree(credential)

    def write(self, target: str, token: str) -> None:
        ctypes, wintypes, CredentialW, _, advapi = self._api()
        encoded = token.encode("utf-8")
        if not encoded or len(encoded) > self._MAX_BLOB_BYTES:
            raise CredentialStoreError("Session token cannot be stored safely")
        blob = (wintypes.BYTE * len(encoded)).from_buffer_copy(encoded)
        credential = CredentialW()
        credential.Type = self._CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(wintypes.BYTE))
        credential.Persist = self._CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "Computer Warrior"
        if not advapi.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError(f"Windows Credential Manager write failed ({ctypes.get_last_error()})")

    def delete(self, target: str) -> None:
        ctypes, _, _, _, advapi = self._api()
        if not advapi.CredDeleteW(target, self._CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != self._ERROR_NOT_FOUND:
                raise CredentialStoreError(f"Windows Credential Manager delete failed ({error})")


def default_credential_store() -> CredentialStore:
    return WindowsCredentialStore() if sys.platform == "win32" else EphemeralCredentialStore()
