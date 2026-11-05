#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""requests 的最小兼容层。

优先使用 requests（如果环境里装了）；没装时退回标准库 urllib，
因此本仓库的更新脚本在任何 Python 3.8+ 直装环境（含 uv/PEP 668 托管的工具链）
下都能直接运行，无需 pip install。

只实现脚本用到的子集：get(url, timeout=...) -> 响应对象
响应对象提供 .content / .text / .json() / .raise_for_status() / .encoding
"""

from __future__ import annotations

import gzip
import json as _json
import ssl
import urllib.error
import urllib.request
import zlib

__all__ = ["get", "HTTPError", "Response", "using_requests"]

try:  # pragma: no cover - 取决于环境
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

using_requests = _requests is not None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) maimai-knowledge-skill/1.0"


class HTTPError(Exception):
    """与 requests.HTTPError 行为一致：raise_for_status() 抛出。"""


class Response:
    def __init__(self, status: int, headers, content: bytes, url: str) -> None:
        self.status_code = status
        self.status = status
        self.headers = headers
        self.content = content
        self.url = url
        self.encoding = None
        self._text = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} error for url: {self.url}")

    @property
    def text(self) -> str:
        if self._text is None:
            encoding = self.encoding or self._charset() or "utf-8"
            try:
                self._text = self.content.decode(encoding, errors="replace")
            except LookupError:
                self._text = self.content.decode("utf-8", errors="replace")
        return self._text

    def _charset(self):
        ctype = (self.headers.get("Content-Type") if self.headers else "") or ""
        for part in ctype.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                return value.strip('"').strip()
        return None

    def json(self):
        return _json.loads(self.content.decode(self.encoding or "utf-8", errors="replace"))


def _decompress(data: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    if encoding == "gzip":
        return gzip.decompress(data)
    if encoding == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            return zlib.decompress(data, -zlib.MAX_WBITS)
    if encoding == "br":  # 极少见；标准库无 brotli，保持原样让上层的解码报错更清晰
        return data
    return data


def get(url: str, timeout: int = 30, **kwargs):
    """GET 请求。有 requests 时走 requests，否则走 urllib。"""
    if _requests is not None:
        return _requests.get(url, timeout=timeout, **kwargs)

    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", USER_AGENT)
    headers.setdefault("Accept", "application/json, text/csv, text/plain, */*")
    headers.setdefault("Accept-Encoding", "gzip, deflate")
    request = urllib.request.Request(url, headers=headers, method="GET")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as raw:
            body = _decompress(raw.read(), raw.headers.get("Content-Encoding", ""))
            return Response(raw.status, raw.headers, body, url)
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也返回响应对象，交由 raise_for_status 处理
        body = _decompress(exc.read() or b"", exc.headers.get("Content-Encoding", "") if exc.headers else "")
        return Response(exc.code, exc.headers, body, url)
