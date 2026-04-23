from __future__ import annotations

import datetime as dt
import os
import threading
import time
from contextlib import contextmanager
from typing import Any

import pandas as pd

PROXY_ENV_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
]

_EXTERNAL_CALL_GATE = threading.Condition()
_ACTIVE_EXTERNAL_CALLS = 0
_NO_PROXY_OVERRIDE_ACTIVE = False


@contextmanager
def _shared_external_call():
    """Allow normal upstream calls to run concurrently unless a no-proxy retry is active."""
    global _ACTIVE_EXTERNAL_CALLS
    with _EXTERNAL_CALL_GATE:
        while _NO_PROXY_OVERRIDE_ACTIVE:
            _EXTERNAL_CALL_GATE.wait()
        _ACTIVE_EXTERNAL_CALLS += 1
    try:
        yield
    finally:
        with _EXTERNAL_CALL_GATE:
            _ACTIVE_EXTERNAL_CALLS -= 1
            if _ACTIVE_EXTERNAL_CALLS == 0:
                _EXTERNAL_CALL_GATE.notify_all()


@contextmanager
def _exclusive_no_proxy_call():
    """Run one no-proxy retry while blocking overlapping shared upstream calls."""
    global _NO_PROXY_OVERRIDE_ACTIVE
    with _EXTERNAL_CALL_GATE:
        while _NO_PROXY_OVERRIDE_ACTIVE or _ACTIVE_EXTERNAL_CALLS > 0:
            _EXTERNAL_CALL_GATE.wait()
        _NO_PROXY_OVERRIDE_ACTIVE = True
    try:
        yield
    finally:
        with _EXTERNAL_CALL_GATE:
            _NO_PROXY_OVERRIDE_ACTIVE = False
            _EXTERNAL_CALL_GATE.notify_all()


@contextmanager
def without_proxy_env():
    """Temporarily clear proxy env vars for flaky proxy environments."""
    backup: dict[str, str | None] = {k: os.environ.get(k) for k in PROXY_ENV_KEYS + ["NO_PROXY", "no_proxy"]}
    try:
        for key in PROXY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _should_retry_without_proxy(exc: Exception) -> bool:
    """Return True when error message indicates proxy-related failure."""
    msg = str(exc).lower()
    return "proxyerror" in msg or "unable to connect to proxy" in msg


def _should_retry_network(exc: Exception) -> bool:
    """Return True when error message suggests transient network instability."""
    msg = str(exc).lower()
    retry_patterns = (
        "connection aborted",
        "remotedisconnected",
        "remote end closed connection without response",
        "max retries exceeded",
        "read timed out",
        "connect timeout",
        "temporarily unavailable",
        "chunkedencodingerror",
    )
    return any(pattern in msg for pattern in retry_patterns)


def _call_with_resilience(func, *args, **kwargs):
    """Call upstream function with retry and proxy-bypass fallback."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with _shared_external_call():
                return func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - upstream/network variability
            last_exc = exc
            if _should_retry_without_proxy(exc):
                try:
                    # Clearing proxy env vars is process-global, so isolate that retry window.
                    with _exclusive_no_proxy_call():
                        with without_proxy_env():
                            return func(*args, **kwargs)
                except Exception as proxy_exc:
                    last_exc = proxy_exc
            if not _should_retry_network(last_exc):
                raise last_exc
            time.sleep(0.8 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def to_float(value: Any) -> float | None:
    """Convert mixed numeric text into float, returning None for invalid values."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)

    text = str(value).strip()
    if not text or text in {"--", "nan", "None"}:
        return None
    text = text.replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def to_date_str(value: Any) -> str | None:
    """Convert many date-like formats into ISO date string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt, text_length in (
        ("%Y-%m-%d", 10),
        ("%Y/%m/%d", 10),
        ("%Y%m%d", 8),
        ("%Y-%m", 7),
        ("%Y/%m", 7),
    ):
        try:
            parsed = dt.datetime.strptime(text[:text_length], fmt)
            if fmt in {"%Y-%m", "%Y/%m"}:
                parsed = parsed.replace(day=1)
            return parsed.date().isoformat()
        except ValueError:
            continue

    try:
        parsed = pd.to_datetime(text)
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
    except Exception:
        return None


def _find_col(columns: list[str], candidates: list[str], exclude: list[str] | None = None) -> str | None:
    """Find the first column containing candidate keywords while avoiding exclusions."""
    exclude = exclude or []
    lowered_exclude = [item.lower() for item in exclude]
    lowered_candidates = [item.lower() for item in candidates]
    for col in columns:
        col_clean = col.replace(" ", "").lower()
        if any(ex in col_clean for ex in lowered_exclude):
            continue
        if any(keyword in col_clean for keyword in lowered_candidates):
            return col
    return None
