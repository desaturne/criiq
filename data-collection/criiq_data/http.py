from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from .config import SETTINGS
from .logging_utils import get_logger

log = get_logger("http")

_session: requests.Session | None = None
_last_request_at: dict[str, float] = {}


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": SETTINGS.user_agent})
        _session = s
    return _session


def _respect_delay(url: str, delay_s: float) -> None:
    host = urlparse(url).netloc
    last = _last_request_at.get(host)
    if last is not None:
        wait = delay_s - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def get(url: str, *, delay_s: float | None = None, stream: bool = False,
        timeout: int | None = None, **kwargs) -> requests.Response:
    delay_s = SETTINGS.cricsheet_delay_s if delay_s is None else delay_s
    timeout = SETTINGS.http_timeout_s if timeout is None else timeout
    last_exc: Exception | None = None
    for attempt in range(1, SETTINGS.http_retries + 1):
        _respect_delay(url, delay_s)
        try:
            resp = session().get(url, stream=stream, timeout=timeout, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < SETTINGS.http_retries:
                backoff = SETTINGS.http_backoff_s * (2 ** (attempt - 1))
                log.warning("GET %s failed (%s); retry %d/%d in %.1fs",
                            url, exc, attempt, SETTINGS.http_retries, backoff)
                time.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def head(url: str, *, delay_s: float | None = None) -> requests.Response | None:
    delay_s = SETTINGS.cricsheet_delay_s if delay_s is None else delay_s
    try:
        _respect_delay(url, delay_s)
        return session().head(url, timeout=SETTINGS.http_timeout_s,
                              allow_redirects=True)
    except requests.RequestException as exc:
        log.warning("HEAD %s failed: %s", url, exc)
        return None
