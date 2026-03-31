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
