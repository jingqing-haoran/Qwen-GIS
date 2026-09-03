"""Safe, bundled-Python window actions for QGIS and KNIME on Windows."""

from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
import shutil
import subprocess
import sys
import unicodedata
from ctypes import wintypes
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ALLOWED_PROCESSES = {
    "qgis": {"qgis-bin", "qgis-ltr-bin", "qgis"},
    "knime": {"knime", "knime64"},
}
ALLOWED_EXECUTABLES = {
    "qgis": ("qgis-ltr-bin.exe", "qgis-bin.exe", "qgis.exe"),
    "knime": ("knime.exe", "knime64.exe"),
}
INVALID_ARGUMENT = "INVALID_ARGUMENT"
AMBIGUOUS = "AMBIGUOUS"
OS_ERROR = "OS_ERROR"
UNAVAILABLE = "UNAVAILABLE"
WM_CLOSE = 0x0010
SW_RESTORE = 9


class InputError(ValueError):
    pass


class StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def _write_response(status: str, platform: str | None, *, exit_code: int = 0,
                    action: str | None = None, code: str | None = None,
                    pid: int | None = None, title: str | None = None,
                    path: str | None = None) -> int:
    response: dict[str, Any] = {"status": status}
    if platform is not None:
        response["platform"] = platform
    if action is not None:
        response["action"] = action
    if code is not None:
        response["code"] = code
    if pid is not None:
        response["pid"] = pid
    if title is not None:
        response["title"] = title
    if path is not None:
        response["path"] = path
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return exit_code


def _normalize_title(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _is_fixture_mode() -> bool:
    return "QWEN_GIS_WINDOW_FIXTURE" in os.environ


def _validate_common(arguments: argparse.Namespace) -> None:
    if arguments.platform not in ALLOWED_PROCESSES:
        raise InputError("platform must be qgis or knime")
    if getattr(arguments, "pid", None) is not None and arguments.pid <= 0:
        raise InputError("pid must be a positive integer")
    title_hint = getattr(arguments, "title_hint", None)
    if title_hint is not None and (not title_hint.strip() or len(title_hint) > 256):
        raise InputError("title hint must be a non-empty string up to 256 characters")
    output = getattr(arguments, "output", None)
    if output is not None and not _is_absolute_path(output):
        raise InputError("output must be an absolute path")


def _is_absolute_path(value: str) -> bool:
    return Path(value).is_absolute() or ntpath.isabs(value)


def _fixture_windows() -> list[dict[str, Any]]:
    try:
        value = json.loads(os.environ["QWEN_GIS_WINDOW_FIXTURE"])
    except (KeyError, json.JSONDecodeError) as error:
        raise OSError("window fixture is invalid") from error
    if not isinstance(value, list):
        raise OSError("window fixture must be a list")
    windows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise OSError("window fixture entries must be objects")
        try:
            windows.append({
                "pid": int(item["pid"]),
                "processName": str(item["processName"]),
                "title": str(item["title"]),
                "handle": int(item["handle"]),
            })
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("window fixture entry is invalid") from error
    return windows


def _windows_api() -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("Windows desktop APIs are unavailable")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (enum_proc, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = (wintypes.HWND,)
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    user32.PrintWindow.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    gdi32.DeleteDC.restype = wintypes.BOOL
    return {"user32": user32, "kernel32": kernel32, "gdi32": gdi32, "enum_proc": enum_proc}


def _process_name(api: dict[str, Any], pid: int) -> str | None:
    handle = api["kernel32"].OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.wintypes.DWORD(len(buffer))
        if not api["kernel32"].QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return ntpath.splitext(ntpath.basename(buffer.value))[0]
    finally:
        api["kernel32"].CloseHandle(handle)


def _native_windows() -> list[dict[str, Any]]:
    api = _windows_api()
    result: list[dict[str, Any]] = []

    @api["enum_proc"]
    def callback(handle: int, _parameter: int) -> bool:
        if not api["user32"].IsWindowVisible(handle):
            return True
        title_length = api["user32"].GetWindowTextLengthW(handle)
        if title_length <= 0:
            return True
        title = ctypes.create_unicode_buffer(title_length + 1)
        if not api["user32"].GetWindowTextW(handle, title, len(title)):
            return True
        pid = wintypes.DWORD()
        api["user32"].GetWindowThreadProcessId(handle, ctypes.byref(pid))
        name = _process_name(api, pid.value)
        if name:
            result.append({"pid": pid.value, "processName": name, "title": title.value, "handle": handle})
        return True

    if not api["user32"].EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def _eligible_windows(platform: str) -> list[dict[str, Any]]:
    windows = _fixture_windows() if _is_fixture_mode() else _native_windows()
    permitted = ALLOWED_PROCESSES[platform]
    return [window for window in windows if window["processName"].casefold() in permitted]


def _select_window(platform: str, pid: int | None, title_hint: str | None) -> tuple[dict[str, Any] | None, bool]:
    candidates = _eligible_windows(platform)
    if not candidates:
        return None, False
    if pid is not None:
        matches = [candidate for candidate in candidates if candidate["pid"] == pid]
        if len(matches) == 1:
            return matches[0], False
    if title_hint is not None:
        normalized_hint = _normalize_title(title_hint)
        matches = [candidate for candidate in candidates if _normalize_title(candidate["title"]) == normalized_hint]
        if len(matches) == 1:
            return matches[0], False
        matches = [
            candidate for candidate in candidates
            if normalized_hint in _normalize_title(candidate["title"])
            or _normalize_title(candidate["title"]) in normalized_hint
        ]
        if len(matches) == 1:
            return matches[0], False
    if len(candidates) == 1:
        return candidates[0], False
    return None, True


def _focus(window: dict[str, Any]) -> None:
    if _is_fixture_mode():
        return
    api = _windows_api()
    api["user32"].ShowWindowAsync(window["handle"], SW_RESTORE)
    if not api["user32"].SetForegroundWindow(window["handle"]):
        raise OSError("Windows denied foreground activation")


def _close(window: dict[str, Any]) -> None:
    if _is_fixture_mode():
        return
    api = _windows_api()
    if not api["user32"].PostMessageW(window["handle"], WM_CLOSE, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def _fixture_executable(platform: str) -> str | None:
    if "QWEN_GIS_EXECUTABLE_FIXTURE" not in os.environ:
        return None
    try:
        fixture = json.loads(os.environ["QWEN_GIS_EXECUTABLE_FIXTURE"])
    except json.JSONDecodeError as error:
        raise OSError("executable fixture is invalid") from error
    if not isinstance(fixture, dict):
        raise OSError("executable fixture must be an object")
    value = fixture.get(platform)
    return str(value) if value else None


def _allowed_executable(platform: str, candidate: str | None) -> str | None:
    if not candidate:
        return None
    if ntpath.basename(candidate).casefold() not in ALLOWED_EXECUTABLES[platform]:
        return None
    return candidate


def _registry_executables(platform: str) -> list[str]:
    import winreg

    candidates: list[str] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                root = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        key = winreg.OpenKey(root, winreg.EnumKey(root, index))
                    except OSError:
                        continue
                    with key:
                        for name in ("DisplayIcon", "InstallLocation"):
                            try:
                                value, _ = winreg.QueryValueEx(key, name)
                            except OSError:
                                continue
                            value = str(value).strip().split(",", 1)[0].strip().strip('"')
                            if name == "InstallLocation":
                                candidates.extend(str(Path(value) / executable) for executable in ALLOWED_EXECUTABLES[platform])
                            else:
                                candidates.append(value)
    return candidates


def _program_files_executables(platform: str) -> list[str]:
    candidates: list[str] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root_value = os.environ.get(variable)
        if not root_value:
            continue
        root = Path(root_value) / "Programs" if variable == "LOCALAPPDATA" else Path(root_value)
        try:
            children = list(root.iterdir())[:128]
        except OSError:
            continue
        for child in children:
            for executable in ALLOWED_EXECUTABLES[platform]:
                candidates.append(str(child / executable))
            if not child.is_dir():
                continue
            try:
                grandchildren = list(child.iterdir())[:128]
            except OSError:
                continue
            for grandchild in grandchildren:
                for executable in ALLOWED_EXECUTABLES[platform]:
                    candidates.append(str(grandchild / executable))
    return candidates


def _find_executable(platform: str) -> str | None:
    fixture = _fixture_executable(platform)
    if "QWEN_GIS_EXECUTABLE_FIXTURE" in os.environ:
        return _allowed_executable(platform, fixture)
    for executable in ALLOWED_EXECUTABLES[platform]:
        found = _allowed_executable(platform, shutil.which(executable))
        if found:
            return found
    if os.name != "nt":
        return None
    for candidate in _registry_executables(platform) + _program_files_executables(platform):
        candidate = _allowed_executable(platform, candidate)
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _write_fixture_png(output: str) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _capture(window: dict[str, Any], output: str) -> None:
    if _is_fixture_mode():
        _write_fixture_png(output)
        return
    api = _windows_api()
    rect = wintypes.RECT()
    if not api["user32"].GetWindowRect(window["handle"], ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise OSError("target window has zero size")
    source_dc = memory_dc = bitmap = previous = None
    try:
        source_dc = api["user32"].GetWindowDC(window["handle"])
        if not source_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        memory_dc = api["gdi32"].CreateCompatibleDC(source_dc)
        bitmap = api["gdi32"].CreateCompatibleBitmap(source_dc, width, height)
        if not memory_dc or not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = api["gdi32"].SelectObject(memory_dc, bitmap)
        if not api["user32"].PrintWindow(window["handle"], memory_dc, 2):
            if not api["user32"].PrintWindow(window["handle"], memory_dc, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        if previous is not None:
            api["gdi32"].SelectObject(memory_dc, previous)
            previous = None
        vendor = Path(__file__).parents[1] / "preview-tools" / "vendor"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from PIL import Image
        class BitmapInfoHeader(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                       ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort), ("biCompression", wintypes.DWORD),
                       ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                       ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        class BitmapInfo(ctypes.Structure):
            _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        api["gdi32"].GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(BitmapInfo), wintypes.UINT)
        api["gdi32"].GetDIBits.restype = ctypes.c_int
        if api["gdi32"].GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0) != height:
            raise ctypes.WinError(ctypes.get_last_error())
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).save(output, "PNG")
    finally:
        if previous is not None and memory_dc:
            api["gdi32"].SelectObject(memory_dc, previous)
        if bitmap:
            api["gdi32"].DeleteObject(bitmap)
        if memory_dc:
            api["gdi32"].DeleteDC(memory_dc)
        if source_dc:
            api["user32"].ReleaseDC(window["handle"], source_dc)


def _selected_response(platform: str, action: str | None, pid: int | None, title_hint: str | None) -> tuple[dict[str, Any] | None, int | None]:
    if os.name != "nt" and not _is_fixture_mode():
        return None, _write_response("unavailable", platform, action=action, code=UNAVAILABLE)
    window, ambiguous = _select_window(platform, pid, title_hint)
    if ambiguous:
        return None, _write_response("ambiguous", platform, exit_code=3, action=action, code=AMBIGUOUS)
    if window is None:
        return None, _write_response("not-running", platform, action=action)
    return window, None


def _run(arguments: argparse.Namespace) -> int:
    _validate_common(arguments)
    if arguments.command == "focus":
        window, response = _selected_response(arguments.platform, None, arguments.pid, arguments.title_hint)
        if response is not None:
            return response
        _focus(window)
        return _write_response("focused", arguments.platform, pid=window["pid"], title=window["title"])
    if arguments.command == "capture":
        window, response = _selected_response(arguments.platform, None, arguments.pid, arguments.title_hint)
        if response is not None:
            return response
        _capture(window, arguments.output)
        return _write_response("captured", arguments.platform, pid=window["pid"], title=window["title"], path=arguments.output)
    if arguments.action == "start":
        if os.name != "nt" and "QWEN_GIS_EXECUTABLE_FIXTURE" not in os.environ:
            return _write_response("unavailable", arguments.platform, action="start", code=UNAVAILABLE)
        executable = _find_executable(arguments.platform)
        if executable is None:
            return _write_response("unavailable", arguments.platform, action="start", code=UNAVAILABLE)
        process = subprocess.Popen([executable], close_fds=True)
        return _write_response("started", arguments.platform, action="start", pid=process.pid)
    window, response = _selected_response(arguments.platform, arguments.action, arguments.pid, None)
    if response is not None:
        return response
    if arguments.action == "status":
        return _write_response("running", arguments.platform, action="status", pid=window["pid"], title=window["title"])
    if arguments.action == "focus":
        _focus(window)
        return _write_response("focused", arguments.platform, action="focus", pid=window["pid"], title=window["title"])
    _close(window)
    return _write_response("closed", arguments.platform, action="close", pid=window["pid"], title=window["title"])


def _parser() -> StrictArgumentParser:
    parser = StrictArgumentParser(add_help=False, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    focus = commands.add_parser("focus", add_help=False, allow_abbrev=False)
    focus.add_argument("--platform", required=True)
    focus.add_argument("--pid", type=int)
    focus.add_argument("--title-hint")
    lifecycle = commands.add_parser("lifecycle", add_help=False, allow_abbrev=False)
    lifecycle.add_argument("--platform", required=True)
    lifecycle.add_argument("--action", required=True, choices=("status", "start", "focus", "close"))
    lifecycle.add_argument("--pid", type=int)
    capture = commands.add_parser("capture", add_help=False, allow_abbrev=False)
    capture.add_argument("--platform", required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--pid", type=int)
    capture.add_argument("--title-hint")
    return parser


def main(argv: list[str] | None = None) -> int:
    platform: str | None = None
    action: str | None = None
    try:
        arguments = _parser().parse_args(argv)
        platform = getattr(arguments, "platform", None)
        action = getattr(arguments, "action", None)
        return _run(arguments)
    except (argparse.ArgumentError, InputError, SystemExit, ValueError):
        return _write_response("error", platform, exit_code=2, action=action, code=INVALID_ARGUMENT)
    except (OSError, subprocess.SubprocessError):
        return _write_response("error", platform, exit_code=1, action=action, code=OS_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
