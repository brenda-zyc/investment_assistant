from __future__ import annotations

import importlib

import pytest


backfill_financial_reports = importlib.import_module("scripts.backfill_financial_reports_from_artifacts")


def test_build_financial_report_row_from_artifact_normalizes_units_and_derives_debt_ratio() -> None:
    artifact = {
        "symbol": "000333",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065145.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-17T06:35:40+00:00",
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": None,
            "total_assets": 608791766000.0,
            "net_assets": 223221305000.0,
            "evidence": [
                {
                    "metric": "revenue",
                    "raw_number": "456,451,731",
                    "unit_context": "千元",
                    "score": 500.0,
                },
                {
                    "metric": "net_profit",
                    "raw_number": "43,945,411",
                    "unit_context": "千元",
                    "score": 500.0,
                },
            ],
        },
    }

    row = backfill_financial_reports._build_financial_report_row_from_artifact(artifact)

    assert row is not None
    assert row["report_year"] == 2025
    assert row["report_date"] == "2025-12-31"
    assert row["revenue"] == 456_451_731_000.0
    assert row["net_profit"] == 43_945_411_000.0
    assert row["roe"] == 19.7
    assert row["debt_ratio"] == pytest.approx((608_791_766_000.0 - 223_221_305_000.0) / 608_791_766_000.0 * 100, rel=1e-6)


def test_build_financial_report_row_from_artifact_infers_amount_unit_from_snippet() -> None:
    artifact = {
        "symbol": "000333",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065145.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-17T06:35:40+00:00",
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": None,
            "total_assets": 608791766000.0,
            "net_assets": 223221305000.0,
            "evidence": [
                {
                    "metric": "revenue",
                    "raw_number": "456,451,731",
                    "score": 500.0,
                    "snippet": "营业收入（千元） 456,451,731 407,149,600 12.11% 372,037,280",
                },
                {
                    "metric": "net_profit",
                    "raw_number": "43,945,411",
                    "score": 500.0,
                    "snippet": "归属于上市公司股东的净利润（千元） 43,945,411 38,537,237 14.03% 33,719,935",
                },
            ],
        },
    }

    row = backfill_financial_reports._build_financial_report_row_from_artifact(artifact)

    assert row is not None
    assert row["revenue"] == 456_451_731_000.0
    assert row["net_profit"] == 43_945_411_000.0


def test_extract_multi_year_financial_rows_from_artifact_uses_primary_metrics_table() -> None:
    artifact = {
        "symbol": "000333",
        "title": "2025年年度报告",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065145.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-17T06:35:40+00:00",
        "report_text": """
六、主要会计数据和财务指标
公司是否需追溯调整或重述以前年度会计数据
□ 是 √ 否
 2025 年 2024 年 本年比上年增减 2023 年
营业收入（千元） 456,451,731 407,149,600 12.11% 372,037,280
归属于上市公司股东的净利润（千元） 43,945,411 38,537,237 14.03% 33,719,935
加权平均净资产收益率 19.70% 21.29% -1.59% 22.23%
 2025 年末 2024 年末 本年末比上年末增减 2023 年末
总资产（千元） 608,791,766 604,351,853 0.73% 486,038,184
归属于上市公司股东的净资产（千元） 223,221,305 216,750,057 2.99% 162,878,825
八、分季度主要财务指标
        """,
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": None,
            "total_assets": 608791766000.0,
            "net_assets": 223221305000.0,
            "evidence": [],
        },
    }

    rows = backfill_financial_reports._extract_multi_year_financial_rows_from_artifact(artifact)

    assert [row["report_date"] for row in rows] == ["2025-12-31", "2024-12-31", "2023-12-31"]
    assert [row["revenue"] for row in rows] == [456_451_731_000.0, 407_149_600_000.0, 372_037_280_000.0]
    assert [row["net_profit"] for row in rows] == [43_945_411_000.0, 38_537_237_000.0, 33_719_935_000.0]
    assert [row["roe"] for row in rows] == [19.7, 21.29, 22.23]
    assert rows[0]["debt_ratio"] == pytest.approx((608_791_766_000.0 - 223_221_305_000.0) / 608_791_766_000.0 * 100, rel=1e-6)
    assert rows[1]["debt_ratio"] == pytest.approx((604_351_853_000.0 - 216_750_057_000.0) / 604_351_853_000.0 * 100, rel=1e-6)
    assert rows[2]["debt_ratio"] == pytest.approx((486_038_184_000.0 - 162_878_825_000.0) / 486_038_184_000.0 * 100, rel=1e-6)


def test_main_backfills_only_symbols_with_missing_year_end_rows(monkeypatch, capsys) -> None:
    official_artifact = {
        "symbol": "000333",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065145.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-17T06:35:40+00:00",
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": None,
            "total_assets": 608791766000.0,
            "net_assets": 223221305000.0,
            "evidence": [
                {"metric": "revenue", "raw_number": "456,451,731", "unit_context": "千元", "score": 500.0},
                {"metric": "net_profit", "raw_number": "43,945,411", "unit_context": "千元", "score": 500.0},
            ],
        },
    }
    unofficial_artifact = {
        "symbol": "000333",
        "document_url": "https://example.com/report.pdf",
        "detail_url": "https://example.com/detail",
        "parsed_at": "2026-04-16T00:00:00+00:00",
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2024,
            "report_date": "2024-12-31",
            "revenue": 1.0,
            "net_profit": 1.0,
            "roe": 1.0,
            "debt_ratio": 1.0,
            "evidence": [],
        },
    }
    already_backfilled_artifact = {
        "symbol": "600519",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065000.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-18T00:00:00+00:00",
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 168838102514.79,
            "net_profit": 82320067101.68,
            "roe": 32.53,
            "debt_ratio": 16.42,
            "evidence": [],
        },
    }
    upserted: list[tuple[str, list[dict]]] = []

    monkeypatch.setattr(backfill_financial_reports, "init_db", lambda: None)
    monkeypatch.setattr(
        backfill_financial_reports,
        "_load_report_artifacts",
        lambda symbols=None: [unofficial_artifact, official_artifact, already_backfilled_artifact],
    )
    monkeypatch.setattr(
        backfill_financial_reports,
        "fetch_financial_reports",
        lambda symbol: (
            [{"report_year": 2025, "report_date": "2025-09-30"}]
            if symbol == "000333"
            else [
                {
                    "report_year": 2025,
                    "report_date": "2025-12-31",
                    "revenue": 168838102514.79,
                    "net_profit": 82320067101.68,
                    "roe": 32.53,
                    "debt_ratio": 16.42,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        backfill_financial_reports,
        "upsert_financial_reports",
        lambda symbol, rows: upserted.append((symbol, rows)),
    )

    backfill_financial_reports.main([])

    assert upserted == [
        (
            "000333",
            [
                {
                    "report_year": 2025,
                    "report_date": "2025-12-31",
                    "revenue": 456_451_731_000.0,
                    "net_profit": 43_945_411_000.0,
                    "roe": 19.7,
                    "debt_ratio": pytest.approx((608_791_766_000.0 - 223_221_305_000.0) / 608_791_766_000.0 * 100, rel=1e-6),
                }
            ],
        )
    ]
    output = capsys.readouterr().out
    assert "financial_report_backfill scanned=3 candidates=2 updated=1 skipped_existing=1 skipped_unofficial=1 invalid=0" in output
    assert "000333: updated 2025-12-31" in output


def test_main_backfills_multiple_year_end_rows_from_one_annual_report(monkeypatch) -> None:
    official_artifact = {
        "symbol": "000333",
        "title": "2025年年度报告",
        "document_url": "https://static.cninfo.com.cn/finalpage/2026-03-31/1225065145.PDF",
        "detail_url": "https://www.cninfo.com.cn/new/disclosure/detail",
        "parsed_at": "2026-04-17T06:35:40+00:00",
        "report_text": """
六、主要会计数据和财务指标
 2025 年 2024 年 本年比上年增减 2023 年
营业收入（千元） 456,451,731 407,149,600 12.11% 372,037,280
归属于上市公司股东的净利润（千元） 43,945,411 38,537,237 14.03% 33,719,935
加权平均净资产收益率 19.70% 21.29% -1.59% 22.23%
 2025 年末 2024 年末 本年末比上年末增减 2023 年末
总资产（千元） 608,791,766 604,351,853 0.73% 486,038,184
归属于上市公司股东的净资产（千元） 223,221,305 216,750,057 2.99% 162,878,825
八、分季度主要财务指标
        """,
        "extracted_metrics": {
            "extraction_version": backfill_financial_reports.REPORT_EXTRACTION_VERSION,
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": None,
            "total_assets": 608791766000.0,
            "net_assets": 223221305000.0,
            "evidence": [],
        },
    }
    upserted: list[tuple[str, list[dict]]] = []

    monkeypatch.setattr(backfill_financial_reports, "init_db", lambda: None)
    monkeypatch.setattr(backfill_financial_reports, "_load_report_artifacts", lambda symbols=None: [official_artifact])
    monkeypatch.setattr(
        backfill_financial_reports,
        "fetch_financial_reports",
        lambda _symbol: [
            {"report_year": 2025, "report_date": "2025-09-30"},
            {"report_year": 2024, "report_date": "2024-09-30"},
            {"report_year": 2023, "report_date": "2023-09-30"},
        ],
    )
    monkeypatch.setattr(
        backfill_financial_reports,
        "upsert_financial_reports",
        lambda symbol, rows: upserted.append((symbol, rows)),
    )

    stats = backfill_financial_reports.run_backfill(["000333"])

    assert stats["updated"] == 3
    assert upserted == [
        (
            "000333",
            [
                {
                    "report_year": 2025,
                    "report_date": "2025-12-31",
                    "revenue": 456_451_731_000.0,
                    "net_profit": 43_945_411_000.0,
                    "roe": 19.7,
                    "debt_ratio": pytest.approx((608_791_766_000.0 - 223_221_305_000.0) / 608_791_766_000.0 * 100, rel=1e-6),
                }
            ],
        ),
        (
            "000333",
            [
                {
                    "report_year": 2024,
                    "report_date": "2024-12-31",
                    "revenue": 407_149_600_000.0,
                    "net_profit": 38_537_237_000.0,
                    "roe": 21.29,
                    "debt_ratio": pytest.approx((604_351_853_000.0 - 216_750_057_000.0) / 604_351_853_000.0 * 100, rel=1e-6),
                }
            ],
        ),
        (
            "000333",
            [
                {
                    "report_year": 2023,
                    "report_date": "2023-12-31",
                    "revenue": 372_037_280_000.0,
                    "net_profit": 33_719_935_000.0,
                    "roe": 22.23,
                    "debt_ratio": pytest.approx((486_038_184_000.0 - 162_878_825_000.0) / 486_038_184_000.0 * 100, rel=1e-6),
                }
            ],
        ),
    ]
def test_needs_backfill_when_existing_year_end_row_has_stale_amounts() -> None:
    existing_rows = [
        {
            "report_year": 2025,
            "report_date": "2025-12-31",
            "revenue": 456451731.0,
            "net_profit": 43945411.0,
            "roe": 19.7,
            "debt_ratio": 63.33371811733735,
        }
    ]
    target_row = {
        "report_year": 2025,
        "report_date": "2025-12-31",
        "revenue": 456_451_731_000.0,
        "net_profit": 43_945_411_000.0,
        "roe": 19.7,
        "debt_ratio": 63.33371811733735,
    }

    assert backfill_financial_reports._needs_backfill(existing_rows, target_row) is True
