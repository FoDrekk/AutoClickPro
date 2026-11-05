"""Minimal HTTPS GET through the Windows WinHTTP API.

The frozen build leaves Python's ``ssl`` module out to stay small. WinHTTP
uses the system certificate store and proxy settings and needs no extra
DLLs. Only GET is implemented, with a response size cap and timeouts.
"""

from __future__ import annotations

import ctypes
import sys
from urllib.parse import urlsplit

IS_WINDOWS = sys.platform == "win32"

MAX_RESPONSE_BYTES = 1_000_000

_ACCESS_TYPE_AUTOMATIC_PROXY = 4
_ACCESS_TYPE_DEFAULT_PROXY = 0
_FLAG_SECURE = 0x00800000
_QUERY_STATUS_CODE = 19
_QUERY_FLAG_NUMBER = 0x20000000


class HttpError(OSError):
    """Network, TLS or HTTP-status failure."""


if IS_WINDOWS:
    from ctypes import wintypes

    _winhttp = ctypes.WinDLL("winhttp", use_last_error=True)

    def _bind(name, restype, *argtypes):
        func = getattr(_winhttp, name)
        func.restype = restype
        func.argtypes = list(argtypes)
        return func

    _HINTERNET = ctypes.c_void_p
    _Open = _bind(
        "WinHttpOpen",
        _HINTERNET,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    )
    _Connect = _bind(
        "WinHttpConnect", _HINTERNET, _HINTERNET, wintypes.LPCWSTR, wintypes.WORD, wintypes.DWORD
    )
    _OpenRequest = _bind(
        "WinHttpOpenRequest", _HINTERNET, _HINTERNET, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
    )  # fmt: skip
    _SetTimeouts = _bind(
        "WinHttpSetTimeouts",
        wintypes.BOOL,
        _HINTERNET,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    )
    _AddHeaders = _bind(
        "WinHttpAddRequestHeaders",
        wintypes.BOOL,
        _HINTERNET,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _Send = _bind(
        "WinHttpSendRequest", wintypes.BOOL, _HINTERNET, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t,
    )  # fmt: skip
    _Receive = _bind("WinHttpReceiveResponse", wintypes.BOOL, _HINTERNET, ctypes.c_void_p)
    _QueryHeaders = _bind(
        "WinHttpQueryHeaders", wintypes.BOOL, _HINTERNET, wintypes.DWORD, wintypes.LPCWSTR,
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    )  # fmt: skip
    _ReadData = _bind(
        "WinHttpReadData",
        wintypes.BOOL,
        _HINTERNET,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    _CloseHandle = _bind("WinHttpCloseHandle", wintypes.BOOL, _HINTERNET)


def _fail(what: str) -> HttpError:
    code = ctypes.get_last_error() if IS_WINDOWS else 0
    return HttpError(code, f"{what} failed (Windows error {code})")


def http_get(
    url: str,
    *,
    timeout: float = 8.0,
    user_agent: str = "AutoClickPro",
    accept: str = "application/json",
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> bytes:
    """GET ``url`` and return the body. Raises HttpError on any failure."""
    if not IS_WINDOWS:
        raise HttpError("Update checks require Windows.")
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise HttpError(f"Unsupported URL: {url!r}")
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    ms = int(timeout * 1000)

    handles: list[int] = []
    try:
        session = _Open(user_agent, _ACCESS_TYPE_AUTOMATIC_PROXY, None, None, 0)
        if not session:
            session = _Open(user_agent, _ACCESS_TYPE_DEFAULT_PROXY, None, None, 0)
        if not session:
            raise _fail("WinHttpOpen")
        handles.append(session)
        _SetTimeouts(session, ms, ms, ms, ms)
        connection = _Connect(session, parts.hostname, port, 0)
        if not connection:
            raise _fail("WinHttpConnect")
        handles.append(connection)
        request = _OpenRequest(connection, "GET", path, None, None, None, _FLAG_SECURE if secure else 0)
        if not request:
            raise _fail("WinHttpOpenRequest")
        handles.append(request)
        headers = f"Accept: {accept}\r\n"
        _AddHeaders(request, headers, len(headers), 0x20000000 | 0x10000000)  # ADD | REPLACE
        if not _Send(request, None, 0, None, 0, 0, 0):
            raise _fail("WinHttpSendRequest")
        if not _Receive(request, None):
            raise _fail("WinHttpReceiveResponse")

        status = wintypes.DWORD()
        size = wintypes.DWORD(ctypes.sizeof(status))
        if not _QueryHeaders(
            request,
            _QUERY_STATUS_CODE | _QUERY_FLAG_NUMBER,
            None,
            ctypes.byref(status),
            ctypes.byref(size),
            None,
        ):
            raise _fail("WinHttpQueryHeaders")
        if status.value != 200:
            raise HttpError(f"Server answered HTTP {status.value}.")

        chunks: list[bytes] = []
        total = 0
        buffer = ctypes.create_string_buffer(16384)
        read = wintypes.DWORD()
        while True:
            if not _ReadData(request, buffer, len(buffer), ctypes.byref(read)):
                raise _fail("WinHttpReadData")
            if read.value == 0:
                break
            total += read.value
            if total > max_bytes:
                raise HttpError("Response is larger than expected.")
            chunks.append(buffer.raw[: read.value])
        return b"".join(chunks)
    finally:
        for handle in reversed(handles):
            _CloseHandle(handle)
