from __future__ import annotations

import sqlite3

from app import db


def test_init_db_migrates_industry_prices_to_source_aware_primary_key(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "investment.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE industry_prices (
            industry TEXT NOT NULL,
            indicator TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            value REAL,
            source TEXT,
            PRIMARY KEY (indicator, trade_date)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO industry_prices (industry, indicator, trade_date, value, source)
        VALUES ('Agriculture', 'legacy_indicator', '2026-04-10', 1.23, 'legacy_source')
        """
    )
    conn.commit()
    conn.close()

    db.init_db()

    conn = sqlite3.connect(db_path)
    pk_rows = conn.execute("PRAGMA table_info('industry_prices')").fetchall()
    pk_columns = [row[1] for row in sorted(pk_rows, key=lambda row: row[5]) if row[5] > 0]
    stored_rows = conn.execute("SELECT indicator, trade_date, source FROM industry_prices").fetchall()
    conn.close()

    assert pk_columns == ["indicator", "trade_date", "source"]
    assert stored_rows == [("legacy_indicator", "2026-04-10", "legacy_source")]


def test_upsert_industry_prices_allows_multiple_sources_for_same_indicator_date(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "investment.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    db.upsert_industry_prices(
        [
            {
                "industry": "Agriculture",
                "indicator": "shared_indicator",
                "trade_date": "2026-04-10",
                "value": 28.5,
                "source": "moa_market_info",
            },
            {
                "industry": "Agriculture",
                "indicator": "shared_indicator",
                "trade_date": "2026-04-10",
                "value": 8.8,
                "source": "spot_hog_lean_price_soozhu",
            },
        ]
    )

    rows = db.fetch_industry_prices("shared_indicator")

    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"moa_market_info", "spot_hog_lean_price_soozhu"}


def test_init_db_creates_report_artifacts_table(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "investment.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    conn.close()

    assert "report_artifacts" in names


def test_report_artifact_round_trip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "investment.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    db.upsert_report_artifact(
        {
            "report_key": "000333|https://static.cninfo.com.cn/report.pdf",
            "symbol": "000333",
            "document_url": "https://static.cninfo.com.cn/report.pdf",
            "detail_url": None,
            "title": "2025年年度报告",
            "published_at": "2026-03-28 20:00:00",
            "content_type": "application/pdf",
            "pdf_pages": 180,
            "report_text": "annual report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [{"id": "profit_authenticity", "summary": "ok"}],
            "llm_analysis": {"summary": "llm note"},
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        }
    )

    stored = db.fetch_report_artifact("000333|https://static.cninfo.com.cn/report.pdf")
    latest = db.fetch_latest_report_artifact_for_symbol("000333")

    assert stored is not None
    assert latest is not None
    assert stored["symbol"] == "000333"
    assert stored["extracted_metrics"]["revenue"] == 100.0
    assert stored["answers"][0]["id"] == "profit_authenticity"
    assert stored["llm_analysis"]["summary"] == "llm note"
    assert latest["report_key"] == stored["report_key"]
