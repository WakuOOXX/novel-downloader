# -*- coding: utf-8 -*-
"""HTTP 抓取层:每个书源独立会话,自动识别编码,统一超时。"""
import threading
import requests
from bs4 import UnicodeDammit

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_sessions = {}
_lock = threading.Lock()


def _session(key: str) -> requests.Session:
    """同一 key(书源名+线程)复用独立 Session,避免 Cookie 串源。"""
    tid = threading.get_ident()
    k = (key, tid)
    with _lock:
        s = _sessions.get(k)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": DEFAULT_UA,
                              "Accept-Language": "zh-CN,zh;q=0.9"})
            s.trust_env = True
            _sessions[k] = s
        return s


def decode_html(raw: bytes) -> str:
    """自动解码:优先 meta/头声明,失败按 gb18030 兜底。"""
    try:
        return UnicodeDammit(raw, ["utf-8", "gb18030", "gbk", "big5"]).unicode_markup or raw.decode("utf-8", "ignore")
    except Exception:
        return raw.decode("utf-8", "ignore")


def fetch(key: str, url: str, method: str = "GET", body=None,
          headers=None, timeout: float = 12.0, referer: str = "") -> tuple:
    """返回 (final_url, text)。失败抛出异常由调用方决定是否吞掉。"""
    s = _session(key)
    kw = dict(timeout=timeout, allow_redirects=True)
    hdrs = {}
    if headers:
        hdrs.update(headers)
    if referer:
        hdrs.setdefault("Referer", referer)
    kw["headers"] = hdrs or None
    if method.upper() == "POST":
        resp = s.post(url, data=body.encode("utf-8") if isinstance(body, str) else body, **kw)
    else:
        resp = s.get(url, **kw)
    resp.raise_for_status()
    return resp.url, decode_html(resp.content)
