from __future__ import annotations

from types import SimpleNamespace

from app.services import llm_service


def test_session_llm_config_round_trip_masks_secret() -> None:
    """Session config helpers should preserve usable config while masking secrets in status output."""
    llm_service.clear_session_llm_config()
    llm_service.set_session_llm_config(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test-123456",
        }
    )

    effective = llm_service.get_effective_llm_config()
    masked = llm_service.get_session_llm_config_masked()

    assert effective["provider"] == "deepseek"
    assert effective["api_key"] == "sk-test-123456"
    assert masked["provider"] == "deepseek"
    assert masked["has_api_key"] is True
    assert masked["api_key_masked"].endswith("3456")
    assert "api_key" not in masked


def test_build_ssl_context_prefers_certifi_bundle(monkeypatch) -> None:
    """LLM HTTPS requests should use certifi's CA bundle when available."""
    recorded: dict[str, object] = {}

    def fake_create_default_context(*, cafile=None, capath=None, cadata=None):
        recorded["cafile"] = cafile
        recorded["capath"] = capath
        recorded["cadata"] = cadata
        return "fake-context"

    monkeypatch.setattr(llm_service.ssl, "create_default_context", fake_create_default_context)
    monkeypatch.setattr(llm_service, "certifi", SimpleNamespace(where=lambda: "/tmp/fake-certifi.pem"))

    context = llm_service._build_ssl_context()

    assert context == "fake-context"
    assert recorded["cafile"] == "/tmp/fake-certifi.pem"


def test_post_chat_completion_passes_ssl_context_to_urlopen(monkeypatch) -> None:
    """Chat completion requests should forward the constructed SSL context to urlopen."""
    captured: dict[str, object] = {}

    class FakeResponse:
        """Minimal context-manager response for urllib tests."""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"status\\": \\"ok\\"}"}}]}'

    monkeypatch.setattr(llm_service, "_build_ssl_context", lambda: "ssl-context")

    def fake_urlopen(request, timeout=None, context=None):
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setattr(llm_service.urllib.request, "urlopen", fake_urlopen)

    result = llm_service._post_chat_completion(
        {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        },
        [{"role": "user", "content": 'Reply with {"status":"ok"}'}],
        timeout_seconds=7,
    )

    assert result["status"] == "ok"
    assert captured["timeout"] == 7
    assert captured["context"] == "ssl-context"


def test_answer_report_question_with_llm_uses_post_chat_completion_and_returns_parsed_json(monkeypatch) -> None:
    """The public report-Q&A helper should assemble context and return parsed JSON from the chat helper."""
    captured: dict[str, object] = {}

    def fake_get_effective_llm_config():
        return {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        }

    def fake_post_chat_completion(config, messages, *, timeout_seconds=20):
        captured["config"] = config
        captured["messages"] = messages
        captured["timeout"] = timeout_seconds
        return {
            "short_answer": "llm answer",
            "evidence": ["e1"],
            "citations": [{"source": "report_text", "snippet": "snippet"}],
            "confidence": "medium",
        }

    monkeypatch.setattr(llm_service, "get_effective_llm_config", fake_get_effective_llm_config)
    monkeypatch.setattr(llm_service, "_post_chat_completion", fake_post_chat_completion)

    result = llm_service.answer_report_question_with_llm(
        report_title="2025年年度报告",
        report_text="report text",
        question="净利润可持续吗？",
        history=[{"role": "user", "content": "what drove growth?"}],
        session_summary="prior summary",
        extracted_metrics={"revenue": 100.0},
        answers=[{"question": "净利润是否可持续？", "summary": "收入和利润增长稳健。"}],
        llm_analysis={"summary": "LLM summary"},
    )

    assert result["short_answer"] == "llm answer"
    assert captured["config"]["model"] == "deepseek-chat"
    assert captured["timeout"] == 20
    assert captured["messages"][0]["role"] == "system"
    assert "report-scoped financial Q&A assistant" in captured["messages"][0]["content"]
