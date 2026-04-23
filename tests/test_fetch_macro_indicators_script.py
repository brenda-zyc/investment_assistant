from __future__ import annotations

from pathlib import Path


def test_fetch_macro_indicators_script_does_not_globally_disable_tls() -> None:
    source = Path("scripts/fetch_macro_indicators.py").read_text(encoding="utf-8")

    assert "_create_default_https_context = ssl._create_unverified_context" not in source
