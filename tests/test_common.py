from __future__ import annotations

import os
import threading

from app.services import common


def test_call_with_resilience_blocks_other_calls_during_no_proxy_retry(monkeypatch) -> None:
    """Other resilience-wrapped calls should not run while proxy env vars are temporarily overridden."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.local:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    inside_no_proxy_retry = threading.Event()
    release_no_proxy_retry = threading.Event()
    observer_entered = threading.Event()
    retry_result: dict[str, tuple[str | None, str | None, str | None]] = {}
    observe_result: dict[str, tuple[str | None, str | None, str | None]] = {}

    call_count = {"retrying": 0}

    def retrying_func() -> tuple[str | None, str | None, str | None]:
        call_count["retrying"] += 1
        if call_count["retrying"] == 1:
            raise RuntimeError("ProxyError: upstream failed")
        inside_no_proxy_retry.set()
        release_no_proxy_retry.wait(timeout=1)
        return (
            os.environ.get("HTTP_PROXY"),
            os.environ.get("NO_PROXY"),
            os.environ.get("no_proxy"),
        )

    def observing_func() -> tuple[str | None, str | None, str | None]:
        observer_entered.set()
        return (
            os.environ.get("HTTP_PROXY"),
            os.environ.get("NO_PROXY"),
            os.environ.get("no_proxy"),
        )

    retry_thread = threading.Thread(
        target=lambda: retry_result.setdefault("value", common._call_with_resilience(retrying_func))
    )
    observe_thread = threading.Thread(
        target=lambda: observe_result.setdefault("value", common._call_with_resilience(observing_func))
    )

    retry_thread.start()
    assert inside_no_proxy_retry.wait(timeout=1), "retry thread never entered no-proxy retry branch"

    observe_thread.start()
    assert not observer_entered.wait(timeout=0.05), "observer should be blocked until proxy env is restored"

    release_no_proxy_retry.set()
    retry_thread.join(timeout=1)
    observe_thread.join(timeout=1)

    assert retry_result["value"] == (None, "*", "*")
    assert observe_result["value"] == ("http://proxy.local:8080", None, None)


def test_to_date_str_parses_compact_yyyymmdd_dates() -> None:
    assert common.to_date_str("20251231") == "2025-12-31"
