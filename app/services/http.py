"""HTTP 请求共用入口：保留环境代理，并支持 Windows 系统 PAC 自动代理。

httpx 支持 HTTP(S)_PROXY，但不会执行 Windows 的自动代理脚本。
使用 WinHTTP 按目标 URL 解析 PAC，无需安装额外依赖或修改系统代理。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import httpx

logger = logging.getLogger("wenshu.http")


def _windows_proxy(url: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    class IEConfig(ctypes.Structure):
        _fields_ = [("auto_detect", wintypes.BOOL), ("pac_url", ctypes.c_void_p),
                    ("proxy", ctypes.c_void_p), ("bypass", ctypes.c_void_p)]

    class AutoProxyOptions(ctypes.Structure):
        _fields_ = [("flags", wintypes.DWORD), ("detect_flags", wintypes.DWORD),
                    ("pac_url", wintypes.LPCWSTR), ("reserved", ctypes.c_void_p),
                    ("reserved_flags", wintypes.DWORD), ("auto_logon", wintypes.BOOL)]

    class ProxyInfo(ctypes.Structure):
        _fields_ = [("access_type", wintypes.DWORD), ("proxy", ctypes.c_void_p),
                    ("bypass", ctypes.c_void_p)]

    winhttp = ctypes.WinDLL("winhttp", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    winhttp.WinHttpGetIEProxyConfigForCurrentUser.argtypes = [ctypes.POINTER(IEConfig)]
    winhttp.WinHttpGetIEProxyConfigForCurrentUser.restype = wintypes.BOOL
    winhttp.WinHttpOpen.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.DWORD]
    winhttp.WinHttpOpen.restype = ctypes.c_void_p
    winhttp.WinHttpSetTimeouts.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int]
    winhttp.WinHttpSetTimeouts.restype = wintypes.BOOL
    winhttp.WinHttpGetProxyForUrl.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                             ctypes.POINTER(AutoProxyOptions),
                                             ctypes.POINTER(ProxyInfo)]
    winhttp.WinHttpGetProxyForUrl.restype = wintypes.BOOL
    winhttp.WinHttpCloseHandle.argtypes = [ctypes.c_void_p]
    winhttp.WinHttpCloseHandle.restype = wintypes.BOOL

    cfg, info = IEConfig(), ProxyInfo()
    session = None
    try:
        if not winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(cfg)):
            return None
        if not cfg.pac_url and not cfg.auto_detect:
            return None  # 静态代理由 httpx/urllib 的环境解析处理。
        session = winhttp.WinHttpOpen("Wenshu/1.0", 1, None, None, 0)
        if not session:
            raise ctypes.WinError(ctypes.get_last_error())
        winhttp.WinHttpSetTimeouts(session, 5000, 5000, 5000, 5000)
        pac_url = ctypes.wstring_at(cfg.pac_url) if cfg.pac_url else None
        options = AutoProxyOptions(
            flags=2 if pac_url else 1, detect_flags=0 if pac_url else 3,
            pac_url=pac_url, auto_logon=True)
        if not winhttp.WinHttpGetProxyForUrl(session, url, ctypes.byref(options),
                                            ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.access_type == 1 or not info.proxy:
            return None  # PAC 为此地址返回 DIRECT。
        return _proxy_for_scheme(ctypes.wstring_at(info.proxy), urlsplit(url).scheme)
    finally:
        if session:
            winhttp.WinHttpCloseHandle(session)
        for pointer in (cfg.pac_url, cfg.proxy, cfg.bypass, info.proxy, info.bypass):
            if pointer:
                kernel32.GlobalFree(pointer)


def _proxy_for_scheme(value: str, scheme: str) -> str | None:
    """WinHTTP 返回 host:port 或 http=host:port;https=host:port。"""
    for entry in value.split(";"):
        entry = entry.strip()
        if "=" in entry:
            key, entry = entry.split("=", 1)
            if key.strip().lower() != scheme:
                continue
        if entry:
            return entry if "://" in entry else "http://" + entry
    return None


@lru_cache(maxsize=128)
def _cached_windows_proxy(url: str, minute: int) -> str | None:
    try:
        return _windows_proxy(url)
    except OSError as exc:
        logger.warning("系统自动代理解析失败，将使用默认网络连接：%s", exc)
        return None


def proxy_for(url: str) -> str | None:
    """显式应用代理 > 标准环境/静态系统代理 > Windows PAC。"""
    explicit = os.environ.get("WENSHU_HTTP_PROXY", "").strip()
    if explicit:
        return explicit
    target = urlsplit(url)
    if sys.platform != "win32" or proxy_bypass(target.netloc):
        return None
    proxies = getproxies()
    if proxies.get(target.scheme) or proxies.get("all"):
        return None  # httpx 自身处理这些代理，保留 NO_PROXY 语义。
    return _cached_windows_proxy(url, int(time.monotonic() // 60))


def client_for(url: str, **kwargs) -> httpx.Client:
    proxy = proxy_for(url)
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def get(url: str, **kwargs) -> httpx.Response:
    return _request("GET", url, **kwargs)


def post(url: str, **kwargs) -> httpx.Response:
    return _request("POST", url, **kwargs)


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    options = {key: kwargs.pop(key) for key in ("timeout", "follow_redirects") if key in kwargs}
    with client_for(url, **options) as client:
        return client.request(method, url, **kwargs)
