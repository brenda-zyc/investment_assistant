from __future__ import annotations

import subprocess

import pytest

from app.services import financial_report_service as report_service
from app.services.financial_report_service import (
    extract_financial_row_from_report_text,
    extract_report_assessment_metrics,
    fetch_report_text_from_url,
    select_latest_annual_report,
)


def test_extract_financial_row_from_chinese_report_text() -> None:
    text = """
    2024年年度报告摘要。公司2024年实现营业收入1,234.56亿元，
    归属于上市公司股东的净利润98.76亿元，净资产收益率15.2%，资产负债率48.6%。
    报告期：2024年12月31日。
    """
    payload = extract_financial_row_from_report_text(text)

    assert payload["report_year"] == 2024
    assert payload["report_date"] == "2024-12-31"
    assert payload["revenue"] == 1234.56 * 100000000
    assert payload["net_profit"] == 98.76 * 100000000
    assert payload["roe"] == 15.2
    assert payload["debt_ratio"] == 48.6
    assert len(payload["evidence"]) >= 4
    for evidence in payload["evidence"]:
        assert "parsed_value" in evidence
        assert "distance" in evidence
        assert "score" in evidence


def test_extract_financial_row_with_sparse_text() -> None:
    text = "这是一个公告页面，但没有关键财务指标。"
    payload = extract_financial_row_from_report_text(text, title="测试公告")

    assert payload["report_year"] is None
    assert payload["revenue"] is None
    assert payload["net_profit"] is None
    assert payload["roe"] is None
    assert payload["debt_ratio"] is None
    assert any("Revenue" in warning for warning in payload["warnings"])


def test_extract_report_assessment_metrics_extracts_quality_fields() -> None:
    text = """
    2024年年度报告。公司2024年实现营业收入1,000亿元，
    归属于上市公司股东的净利润120亿元，
    归属于上市公司股东的扣除非经常性损益的净利润110亿元，
    经营活动产生的现金流量净额130亿元，
    购建固定资产、无形资产和其他长期资产支付的现金40亿元，
    净资产收益率16.5%，资产负债率45.1%。
    报告期：2024年12月31日。
    """
    payload = extract_report_assessment_metrics(text)

    assert payload["report_year"] == 2024
    assert payload["report_date"] == "2024-12-31"
    assert payload["deducted_net_profit"] == 110 * 100000000
    assert payload["operating_cash_flow"] == 130 * 100000000
    assert payload["capex_cash_outflow"] == 40 * 100000000
    assert len(payload["evidence"]) >= 7


def test_extract_report_assessment_metrics_prefers_title_year_over_future_mentions() -> None:
    text = """
    2026年3月发布。公司计划在2028年继续扩大海外业务。
    报告期内公司实现营业收入4,585亿元，归母净利润439.5亿元，
    加权平均净资产收益率19.70%，资产负债率60.54%。
    """
    payload = extract_report_assessment_metrics(text, title="2025年年度报告")

    assert payload["report_year"] == 2025
    assert payload["report_date"] == "2025-12-31"


def test_extract_report_assessment_metrics_rejects_unitless_cash_flow_amount() -> None:
    text = """
    2025年年度报告。营业收入4,585亿元，归母净利润439.5亿元，
    资产负债率60.54%，加权平均净资产收益率19.70%。
    经营活动产生的现金流量净额 14,320,968 22,960,047 19,785,070 -3,720,155。
    """
    payload = extract_report_assessment_metrics(text, title="2025年年度报告")

    assert payload["operating_cash_flow"] is None
    assert "Operating cash flow was not reliably extracted." in payload["warnings"]


def test_select_latest_annual_report_prefers_full_report() -> None:
    candidates = [
        {
            "title": "2024年年度报告摘要",
            "published_at": "2025-03-20 18:00:00",
            "detail_url": "a",
            "document_url": "a.pdf",
        },
        {
            "title": "2024年年度报告",
            "published_at": "2025-03-20 18:01:00",
            "detail_url": "b",
            "document_url": "b.pdf",
        },
        {
            "title": "2023年年度报告",
            "published_at": "2024-03-18 09:00:00",
            "detail_url": "c",
            "document_url": "c.pdf",
        },
    ]

    selected = select_latest_annual_report(candidates)
    assert selected is not None
    assert selected["document_url"] == "b.pdf"


class _DummyResponse:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self.headers = {"Content-Type": content_type}

    def read(self, _size: int = -1) -> bytes:
        return self._payload

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_fetch_report_text_from_url_pdf_branch(monkeypatch) -> None:
    dummy_pdf_bytes = b"%PDF-1.4 FAKE"

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        assert timeout == 12
        assert context is not None
        return _DummyResponse(dummy_pdf_bytes, "application/pdf")

    def fake_extract_pdf_text(raw: bytes, max_pages: int = 120):  # noqa: ANN001
        assert raw == dummy_pdf_bytes
        assert max_pages == 120
        return ("2024年 营业收入 100 亿元 净利润 10 亿元 ROE 15% 资产负债率 45%", 88)

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.setattr(report_service, "_extract_pdf_text", fake_extract_pdf_text)

    out = fetch_report_text_from_url("https://example.com/reports/annual-2024.pdf")
    assert out["content_type"] == "application/pdf"
    assert out["title"] == "annual-2024.pdf"
    assert out["pdf_pages"] == 88
    assert out["tls_insecure"] is False
    assert "营业收入" in out["text"]


def test_extract_pdf_text_without_available_parser(monkeypatch) -> None:
    monkeypatch.setattr(report_service, "PdfReader", None)
    monkeypatch.setattr(report_service.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError) as exc_info:
        report_service._extract_pdf_text(b"%PDF-1.4 fake")
    assert "Failed to parse PDF text" in str(exc_info.value)


def test_extract_pdf_text_rejects_raw_pdf_structure_dump(monkeypatch) -> None:
    monkeypatch.setattr(report_service, "PdfReader", None)
    monkeypatch.setattr(report_service.shutil, "which", lambda _name: "/usr/bin/textutil")

    def fake_run(*_args, **_kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=["textutil"],
            returncode=0,
            stdout=(
                "%PDF-1.7\n"
                "1 0 obj\n"
                "<</Type/Catalog/Pages 2 0 R>>\n"
                "stream\n"
                "BT /F1 12 Tf ET\n"
                "endstream\n"
                "endobj\n"
                "xref\n"
                "trailer\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(report_service.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        report_service._extract_pdf_text(b"%PDF-1.4 fake")
    assert "Failed to parse PDF text" in str(exc_info.value)
    assert "unreadable" in str(exc_info.value).lower()


def test_fetch_report_text_from_url_ssl_verify_failure_with_hint(monkeypatch) -> None:
    class _SslVerifyError(Exception):
        pass

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        _ = timeout, context
        raise RuntimeError("certificate verify failed")

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.delenv("REPORT_URL_INSECURE_SSL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        fetch_report_text_from_url("https://example.com/report.pdf")
    assert "TLS certificate verification failed" in str(exc_info.value)


def test_fetch_report_text_from_url_pdf_size_limit(monkeypatch) -> None:
    payload = b"%PDF-1.4 " + (b"A" * 1_000_100)

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        _ = timeout, context
        return _DummyResponse(payload, "application/pdf")

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.setenv("REPORT_PDF_MAX_MB", "1")

    with pytest.raises(RuntimeError) as exc_info:
        fetch_report_text_from_url("https://example.com/big.pdf")
    assert "PDF file is too large to parse" in str(exc_info.value)
