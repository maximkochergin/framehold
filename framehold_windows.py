"""Windows-only adapters. No shell invocation or third-party runtime packages."""

from __future__ import annotations

import ctypes as ct
import json
import os
import re
import subprocess
import winreg
from contextlib import contextmanager
from ctypes import wintypes as wt

from framehold_core import TweakError, legacy_to_snapshot, valid_guid, validate_snapshot

kernel32 = ct.WinDLL("kernel32", use_last_error=True)
advapi32 = ct.WinDLL("advapi32", use_last_error=True)
shell32 = ct.WinDLL("shell32", use_last_error=True)

GAME_MODE_PATH = r"Software\Microsoft\GameBar"
GAME_MODE_NAME = "AutoGameModeEnabled"
STATE_ROOT = r"Software\framehold\state"
GAME_EXE = "fortniteclient-win64-shipping.exe"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_INFORMATION = 0x0200
TOKEN_QUERY = 0x0008
TH32CS_SNAPPROCESS = 0x00000002
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000


class PROCESSENTRY32W(ct.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ct.c_size_t), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.GetCurrentProcessId.restype = wt.DWORD
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.ReleaseMutex.argtypes = [wt.HANDLE]
kernel32.LocalFree.argtypes = [ct.c_void_p]
kernel32.LocalFree.restype = ct.c_void_p
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ct.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ct.POINTER(PROCESSENTRY32W)]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)]
kernel32.GetPriorityClass.argtypes = [wt.HANDLE]
kernel32.GetPriorityClass.restype = wt.DWORD
kernel32.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.ProcessIdToSessionId.argtypes = [wt.DWORD, ct.POINTER(wt.DWORD)]
kernel32.GetSystemDirectoryW.argtypes = [wt.LPWSTR, wt.UINT]
kernel32.CreateMutexW.argtypes = [ct.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD)]
advapi32.ConvertSidToStringSidW.argtypes = [ct.c_void_p, ct.POINTER(wt.LPWSTR)]
shell32.IsUserAnAdmin.restype = wt.BOOL


def _close(handle):
    if handle:
        kernel32.CloseHandle(handle)


def _sid_for_handle(process_handle) -> str:
    token = wt.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ct.byref(token)):
        raise OSError(ct.get_last_error(), "cannot read process token")
    try:
        size = wt.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ct.byref(size))
        buffer = ct.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ct.byref(size)):
            raise OSError(ct.get_last_error(), "cannot read account id")
        sid_pointer = ct.cast(buffer, ct.POINTER(ct.c_void_p))[0]
        sid_string = wt.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_pointer, ct.byref(sid_string)):
            raise OSError(ct.get_last_error(), "cannot format account id")
        try:
            return sid_string.value
        finally:
            kernel32.LocalFree(sid_string)
    finally:
        _close(token)


def current_sid() -> str:
    return _sid_for_handle(kernel32.GetCurrentProcess())


def _processes():
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wt.HANDLE(-1).value:
        raise OSError(ct.get_last_error(), "cannot list processes")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ct.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ct.byref(entry)):
            return
        while True:
            yield entry.th32ProcessID, entry.szExeFile.lower()
            if not kernel32.Process32NextW(snapshot, ct.byref(entry)):
                break
    finally:
        _close(snapshot)


def _session_id(pid: int) -> int | None:
    session = wt.DWORD()
    if not kernel32.ProcessIdToSessionId(pid, ct.byref(session)):
        return None
    return session.value


def _system_powercfg() -> str:
    buffer = ct.create_unicode_buffer(32768)
    length = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise TweakError("cannot find the windows system directory")
    return os.path.join(buffer.value, "powercfg.exe")


class WindowsBackend:
    def __init__(self):
        self.owner_sid = current_sid()
        self.powercfg = _system_powercfg()

    def check_account(self):
        if not shell32.IsUserAnAdmin():
            raise TweakError("administrator rights are required for changes")
        own_session = _session_id(kernel32.GetCurrentProcessId())
        shell_sids = set()
        for pid, name in _processes():
            if name != "explorer.exe" or _session_id(pid) != own_session:
                continue
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            try:
                shell_sids.add(_sid_for_handle(handle))
            except OSError:
                pass
            finally:
                _close(handle)
        if not shell_sids:
            raise TweakError("cannot verify the signed-in account; no settings were changed")
        if shell_sids != {self.owner_sid}:
            raise TweakError("this elevated window belongs to another account; sign in with your own admin account")

    def _power(self, command: str, *args: str) -> str:
        result = subprocess.run(
            [self.powercfg, command, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise TweakError(f"windows rejected powercfg {command}")
        return result.stdout

    def get_active_plan(self) -> str:
        match = re.search(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", self._power("/getactivescheme"))
        if not match:
            raise TweakError("cannot read the active power plan")
        return match.group().lower()

    def has_plan(self, guid: str) -> bool:
        if not valid_guid(guid):
            raise TweakError("invalid power plan id")
        return guid.lower() in self._power("/list").lower()

    def set_active_plan(self, guid: str):
        if not valid_guid(guid):
            raise TweakError("invalid power plan id")
        self._power("/setactive", guid)
        if self.get_active_plan() != guid.lower():
            raise TweakError("windows did not activate the requested power plan")

    def get_game_mode(self) -> dict:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GAME_MODE_PATH) as key:
                value, kind = winreg.QueryValueEx(key, GAME_MODE_NAME)
        except FileNotFoundError:
            return {"exists": False, "value": None, "kind": None}
        return {"exists": True, "value": value, "kind": "dword" if kind == winreg.REG_DWORD else "other"}

    def set_game_mode(self, value: int):
        if value not in (0, 1):
            raise TweakError("invalid game mode value")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, GAME_MODE_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, GAME_MODE_NAME, 0, winreg.REG_DWORD, value)

    def remove_game_mode(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GAME_MODE_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, GAME_MODE_NAME)
        except FileNotFoundError:
            pass

    def find_game(self) -> list[int]:
        return [pid for pid, name in _processes() if name == GAME_EXE]

    def focus_game(self) -> list[str]:
        self.check_account()
        messages = []
        for pid in self.find_game():
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION, False, pid)
            if not handle:
                messages.append(f"process {pid}: access denied or game closed")
                continue
            try:
                buffer = ct.create_unicode_buffer(32768)
                size = wt.DWORD(len(buffer))
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ct.byref(size)):
                    messages.append(f"process {pid}: identity could not be checked")
                    continue
                path = buffer.value.lower().replace("/", "\\")
                if not path.endswith("\\fortnitegame\\binaries\\win64\\" + GAME_EXE):
                    messages.append(f"process {pid}: not a fortnite install; skipped")
                    continue
                if kernel32.GetPriorityClass(handle) == ABOVE_NORMAL_PRIORITY_CLASS:
                    messages.append(f"process {pid}: already above normal")
                    continue
                if not kernel32.SetPriorityClass(handle, ABOVE_NORMAL_PRIORITY_CLASS):
                    messages.append(f"process {pid}: access denied")
                    continue
                messages.append(f"process {pid}: above normal until the game exits")
            finally:
                _close(handle)
        return messages or ["fortnite is not running"]


class RegistryStore:
    def __init__(self, owner_sid: str):
        self.owner_sid = owner_sid
        self.path = STATE_ROOT + "\\" + owner_sid

    @contextmanager
    def lock(self):
        handle = kernel32.CreateMutexW(None, False, "Global\\framehold-" + self.owner_sid)
        if not handle:
            raise TweakError("cannot lock settings")
        try:
            result = kernel32.WaitForSingleObject(handle, 10000)
            if result not in (0, 0x80):
                raise TweakError("another framehold session is changing settings")
            try:
                yield
            finally:
                kernel32.ReleaseMutex(handle)
        finally:
            _close(handle)

    def read(self) -> dict | None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.path, 0, winreg.KEY_READ) as key:
                raw, kind = winreg.QueryValueEx(key, "snapshot")
        except FileNotFoundError:
            return None
        if kind != winreg.REG_SZ or not isinstance(raw, str) or len(raw) > 8192:
            raise TweakError("saved state has an invalid registry type")
        try:
            return validate_snapshot(json.loads(raw), self.owner_sid)
        except (ValueError, TypeError) as error:
            raise TweakError("saved state is unreadable") from error

    def legacy_pending(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.path, 0, winreg.KEY_READ) as key:
                marker, kind = winreg.QueryValueEx(key, "legacy_resolved")
                if kind == winreg.REG_DWORD and marker == 1:
                    return False
        except FileNotFoundError:
            pass
        return os.path.isfile(self._legacy_path())

    def _legacy_path(self) -> str:
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "fortnite-tweaker", "snapshot.json")

    def import_legacy(self) -> bool:
        if not self.legacy_pending():
            return False
        try:
            with open(self._legacy_path(), "r", encoding="utf-8-sig") as source:
                legacy = json.load(source)
        except (OSError, ValueError) as error:
            raise TweakError("old saved state is unreadable; inspect the legacy snapshot") from error
        state = legacy_to_snapshot(legacy, self.owner_sid)
        self.save_new(state)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "legacy_resolved", 0, winreg.REG_DWORD, 1)
        return True

    def save_new(self, data: dict):
        validate_snapshot(data, self.owner_sid)
        if self.read() is not None:
            raise TweakError("a saved profile already exists")
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, self.path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            winreg.SetValueEx(key, "snapshot", 0, winreg.REG_SZ, json.dumps(data, separators=(",", ":")))

    def clear(self):
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "snapshot")
