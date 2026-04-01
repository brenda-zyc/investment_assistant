from __future__ import annotations

import json
import os
import ssl
import threading
import urllib.error
import urllib.request
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for environments where certifi is absent
    certifi = None


_SESSION_LOCK = threading.Lock()
_SESSION_LLM_CONFIG: dict[str, str] = {}


def _normalize_llm_config(config: dict[str, Any]) -> dict[str, str]:
    """Validate and normalize a provider configuration payload."""
    provider = str(config.get("provider") or "deepseek").strip().lower()
    base_url = str(config.get("base_url") or "").strip().rstrip("/")
    model = str(config.get("model") or "").strip()
    api_key = str(config.get("api_key") or "").strip()

    if not provider:
        raise ValueError("provider is required")
    if not base_url:
        raise ValueError("base_url is required")
    if not model:
        raise ValueError("model is required")
    if not api_key:
        raise ValueError("api_key is required")

    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def _mask_api_key(api_key: str) -> str:
    """Return a masked representation that preserves only the tail for operator checks."""
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * (len(api_key) - 4)}{api_key[-4:]}"


def set_session_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    """Store the normalized LLM configuration in backend process memory."""
    normalized = _normalize_llm_config(config)
    with _SESSION_LOCK:
        _SESSION_LLM_CONFIG.clear()
        _SESSION_LLM_CONFIG.update(normalized)
    return get_session_llm_config_masked()


def clear_session_llm_config() -> None:
    """Clear any in-memory LLM session configuration."""
    with _SESSION_LOCK:
        _SESSION_LLM_CONFIG.clear()


def get_session_llm_config_masked() -> dict[str, Any]:
    """Return a non-sensitive view of the current session configuration."""
    with _SESSION_LOCK:
        current = dict(_SESSION_LLM_CONFIG)

    if not current:
        return {
            "configured": False,
            "provider": None,
            "base_url": None,
            "model": None,
            "has_api_key": False,
            "api_key_masked": None,
        }

    return {
        "configured": True,
        "provider": current.get("provider"),
        "base_url": current.get("base_url"),
        "model": current.get("model"),
        "has_api_key": bool(current.get("api_key")),
        "api_key_masked": _mask_api_key(current.get("api_key", "")),
    }


def get_effective_llm_config() -> dict[str, str] | None:
    """Return session config first, then environment fallback if present."""
    with _SESSION_LOCK:
        if _SESSION_LLM_CONFIG:
            return dict(_SESSION_LLM_CONFIG)

    provider = (os.getenv("LLM_PROVIDER") or "deepseek").strip().lower()
    base_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    model = (os.getenv("LLM_MODEL") or "").strip()
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    if not (base_url and model and api_key):
        return None
    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def _build_ssl_context() -> ssl.SSLContext:
    """Build an HTTPS context that prefers certifi's CA bundle when available."""
    # TLS handling rule: prefer certifi because the local Python framework CA file may be stale or incomplete.
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _post_chat_completion(
    config: dict[str, str],
    messages: list[dict[str, str]],
    *,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    """Send one OpenAI-compatible chat completion request and parse JSON response."""
    request_url = f"{config['base_url']}/chat/completions"
    payload = {
        "model": config["model"],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    request = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=_build_ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM HTTP error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM connection failed: {exc.reason}") from exc

    parsed = json.loads(raw)
    content = (
        parsed.get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )
    if not content:
        raise RuntimeError("LLM response did not contain message content")
    return json.loads(content)


def test_llm_connection(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate that the configured provider can answer a minimal JSON-only prompt."""
    effective = _normalize_llm_config(config) if config is not None else get_effective_llm_config()
    if not effective:
        raise ValueError("No LLM configuration is available")

    result = _post_chat_completion(
        effective,
        [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": 'Reply with {"status":"ok"}'},
        ],
    )
    if result.get("status") != "ok":
        raise RuntimeError("LLM test connection returned an unexpected payload")

    return {
        "ok": True,
        "provider": effective["provider"],
        "model": effective["model"],
    }


def interpret_annual_report_text(
    *,
    symbol: str,
    symbol_name: str | None,
    report_title: str | None,
    report_text: str,
    current_mode: str,
) -> dict[str, Any]:
    """Return LLM-generated textual interpretation for annual-report reading."""
    effective = get_effective_llm_config()
    if not effective:
        raise ValueError("No LLM configuration is available")

    # API assumption: the first provider target is DeepSeek via an OpenAI-compatible endpoint.
    prompt = {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "report_title": report_title,
        "current_mode": current_mode,
        "task": "Summarize the report text and provide concise interpretation for the three questions.",
        "output_schema": {
            "summary": "string",
            "question_notes": [
                {
                    "question_id": "profit_authenticity | profit_sustainability | capital_intensity",
                    "summary": "string",
                    "evidence": ["string"],
                }
            ],
        },
        "constraints": [
            "Use only the provided report text.",
            "Do not invent numbers not grounded in the text.",
            "Return JSON only.",
        ],
        "report_text": report_text[:12000],
    }

    return _post_chat_completion(
        effective,
        [
            {"role": "system", "content": "You are a financial report reading assistant. Return JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )


def answer_report_question_with_llm(
    *,
    report_title: str | None,
    report_text: str,
    question: str,
    history: list[dict[str, str]],
    session_summary: str,
    extracted_metrics: dict[str, Any],
    answers: list[dict[str, Any]],
    llm_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Answer one report-scoped question using the configured chat-completion provider."""
    effective = get_effective_llm_config()
    if not effective:
        raise ValueError("No LLM configuration is available")

    prompt = {
        "task": "Answer one question about the currently active annual report only.",
        "question": question,
        "session_summary": session_summary,
        "history": history,
        "report_title": report_title,
        "extracted_metrics": extracted_metrics,
        "three_questions": answers,
        "llm_reading_notes": llm_analysis,
        "report_text": report_text[:16000],
        "constraints": [
            "Use only the provided annual-report context.",
            "Do not give buy or sell advice.",
            "Return JSON only.",
        ],
    }
    return _post_chat_completion(
        effective,
        [
            {"role": "system", "content": "You are a report-scoped financial Q&A assistant. Return JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
