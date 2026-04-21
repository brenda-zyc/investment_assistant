# Financial Report Context Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract one shared report-context mapper so the financial report usecase and report Q&A service stop maintaining duplicate artifact/context conversion logic.

**Architecture:** Introduce a small pure helper module for `report_key`, `artifact row -> context`, and `context payload -> artifact row` conversion. Keep in-memory cache ownership inside `report_qa_service`, keep orchestration inside `financial_report_usecase`, and move only the duplicated serialization boundary into the new module.

**Tech Stack:** Python 3, FastAPI app structure, SQLite artifact persistence, pytest, monkeypatch-based unit tests

---

## File Map

- Create: `app/services/report_context_service.py`
  Responsibility: pure helpers for report artifact serialization and context reconstruction
- Create: `tests/test_report_context_service.py`
  Responsibility: focused tests for shared mapper behavior
- Modify: `app/services/report_qa_service.py`
  Responsibility: consume shared context mapper, keep hot-cache and Q&A scope logic only
- Modify: `app/usecases/financial_report_usecase.py`
  Responsibility: consume shared context mapper, keep persistence/orchestration only
- Modify: `tests/test_report_qa_service.py`
  Responsibility: preserve persisted-artifact reload behavior through the new shared mapper
- Modify: `tests/test_financial_report_usecase.py`
  Responsibility: preserve URL-analysis/autoread artifact reuse behavior through the new shared mapper
- Optional verify only: `tests/test_financial_report_api.py`
  Responsibility: guard the API surface after the refactor

### Task 1: Introduce Shared Report Context Mapper

**Files:**
- Create: `app/services/report_context_service.py`
- Test: `tests/test_report_context_service.py`

- [ ] **Step 1: Write the failing mapper tests**

```python
from __future__ import annotations

import datetime as dt

from app.services import report_context_service


def test_build_report_key_prefers_document_url() -> None:
    assert (
        report_context_service.build_report_key(
            "000333",
            {
                "document_url": "https://example.com/report.pdf",
                "detail_url": "https://example.com/detail",
            },
        )
        == "000333|https://example.com/report.pdf"
    )


def test_context_from_artifact_row_rebuilds_report_shape() -> None:
    row = {
        "symbol": "000333",
        "title": "2025年年度报告",
        "published_at": "2026-03-28 18:00:00",
        "detail_url": "https://example.com/detail",
        "document_url": "https://example.com/report.pdf",
        "content_type": "application/pdf",
        "pdf_pages": 188,
        "report_text": "annual report text",
        "extracted_metrics": {"revenue": 100.0},
        "answers": [{"id": "profit_authenticity"}],
        "llm_analysis": {"summary": "ok"},
    }

    context = report_context_service.context_from_artifact_row(row)

    assert context["symbol"] == "000333"
    assert context["report"]["document_url"] == "https://example.com/report.pdf"
    assert context["answers"] == [{"id": "profit_authenticity"}]


def test_artifact_row_from_context_appends_extraction_version_and_mode() -> None:
    row = report_context_service.artifact_row_from_context(
        symbol="000333",
        report={
            "title": "2025年年度报告",
            "document_url": "https://example.com/report.pdf",
            "detail_url": "https://example.com/detail",
            "published_at": "2026-03-28 18:00:00",
            "content_type": "application/pdf",
            "pdf_pages": 188,
        },
        report_text="annual report text",
        extracted_metrics={"revenue": 100.0},
        answers=[{"id": "profit_authenticity"}],
        llm_analysis=None,
        extraction_version="v-test",
        has_usable_report_metrics=True,
        now=dt.datetime(2026, 4, 17, tzinfo=dt.UTC),
    )

    assert row["report_key"] == "000333|https://example.com/report.pdf"
    assert row["extracted_metrics"]["extraction_version"] == "v-test"
    assert row["current_mode"] == "report_text_extracted"
    assert row["parsed_at"] == "2026-04-17T00:00:00+00:00"
```

- [ ] **Step 2: Run the new tests and verify failure**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_context_service.py`

Expected: FAIL with `ModuleNotFoundError` or missing attribute errors for `report_context_service`

- [ ] **Step 3: Write the minimal shared mapper implementation**

```python
from __future__ import annotations

import datetime as dt
from typing import Any


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    symbol_text = str(symbol or "").strip()
    if not symbol_text or not report:
        return None
    source_url = report.get("document_url") or report.get("detail_url")
    source_text = str(source_url or "").strip()
    if not source_text:
        return None
    return f"{symbol_text}|{source_text}"


def context_from_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "report": {
            "title": row.get("title"),
            "published_at": row.get("published_at"),
            "detail_url": row.get("detail_url"),
            "document_url": row.get("document_url"),
            "content_type": row.get("content_type"),
            "pdf_pages": row.get("pdf_pages"),
        },
        "report_text": row.get("report_text"),
        "extracted_metrics": row.get("extracted_metrics") or {},
        "answers": row.get("answers") or [],
        "llm_analysis": row.get("llm_analysis"),
    }


def artifact_row_from_context(
    *,
    symbol: str | None,
    report: dict[str, Any] | None,
    report_text: str | None,
    extracted_metrics: dict[str, Any] | None,
    answers: list[dict[str, Any]] | None,
    llm_analysis: dict[str, Any] | None,
    extraction_version: str,
    has_usable_report_metrics: bool,
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    if not symbol or not report_text:
        return None
    report_key = build_report_key(symbol, report)
    if not report_key:
        return None
    timestamp = now or dt.datetime.now(dt.UTC)
    return {
        "report_key": report_key,
        "symbol": symbol,
        "document_url": (report or {}).get("document_url"),
        "detail_url": (report or {}).get("detail_url"),
        "title": (report or {}).get("title"),
        "published_at": (report or {}).get("published_at"),
        "content_type": (report or {}).get("content_type"),
        "pdf_pages": (report or {}).get("pdf_pages"),
        "report_text": report_text,
        "extracted_metrics": {
            **(extracted_metrics or {}),
            "extraction_version": extraction_version,
        },
        "answers": answers or [],
        "llm_analysis": llm_analysis,
        "current_mode": "report_text_extracted" if has_usable_report_metrics else "historical_fallback",
        "parsed_at": timestamp.isoformat(timespec="seconds"),
    }
```

- [ ] **Step 4: Run the mapper tests and verify pass**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_context_service.py`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_context_service.py app/services/report_context_service.py
git commit -m "refactor(report): add shared report context mapper"
```

### Task 2: Switch Report Q&A Service to the Shared Mapper

**Files:**
- Modify: `app/services/report_qa_service.py`
- Modify: `tests/test_report_qa_service.py`
- Test: `tests/test_report_context_service.py`

- [ ] **Step 1: Add the failing service regression test**

Append to `tests/test_report_qa_service.py`:

```python
def test_answer_report_question_rehydrates_context_via_shared_mapper(monkeypatch) -> None:
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(
        report_qa_service,
        "fetch_report_artifact",
        lambda report_key: {
            "report_key": report_key,
            "symbol": "000333",
            "document_url": "https://example.com/report.pdf",
            "detail_url": "https://example.com/detail",
            "title": "2025年年度报告",
            "published_at": "2026-03-28 18:00:00",
            "content_type": "application/pdf",
            "pdf_pages": 188,
            "report_text": "annual report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [],
            "llm_analysis": None,
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://example.com/report.pdf",
        question="收入怎么样？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    cached = report_qa_service.get_cached_report_context(payload["report_key"])
    assert cached is not None
    assert cached["report"]["detail_url"] == "https://example.com/detail"
```

- [ ] **Step 2: Run the targeted Q&A regression test**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py -k rehydrate`

Expected: PASS before the refactor or FAIL after import rewiring if the shared mapper is not fully connected yet

- [ ] **Step 3: Replace private conversion logic with shared helpers**

In `app/services/report_qa_service.py`:

```python
from app.services.report_context_service import build_report_key as build_report_key_shared
from app.services.report_context_service import context_from_artifact_row


def build_report_key(symbol: str, report: dict[str, Any] | None) -> str | None:
    return build_report_key_shared(symbol, report)


# delete _context_from_artifact(...)

artifact = fetch_report_artifact(report_key)
if artifact:
    context = context_from_artifact_row(artifact)
    store_report_context(report_key, context)
```

Keep these functions in `report_qa_service.py` unchanged:
- `clear_report_context_cache`
- `store_report_context`
- `get_cached_report_context`
- all scope classification and LLM fallback code

- [ ] **Step 4: Run Q&A tests**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_context_service.py tests/test_report_qa_service.py`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/report_qa_service.py tests/test_report_qa_service.py tests/test_report_context_service.py
git commit -m "refactor(report): route report qa through shared context mapper"
```

### Task 3: Switch Financial Report Usecase to the Shared Mapper

**Files:**
- Modify: `app/usecases/financial_report_usecase.py`
- Modify: `tests/test_financial_report_usecase.py`
- Test: `tests/test_report_context_service.py`

- [ ] **Step 1: Add the failing persistence regression test**

Append to `tests/test_financial_report_usecase.py`:

```python
def test_persisted_artifact_rehydrates_same_hot_context_shape(monkeypatch) -> None:
    report_qa_service.clear_report_context_cache()
    captured: dict[str, object] = {"row": None}

    monkeypatch.setattr(
        financial_report_usecase,
        "upsert_report_artifact",
        lambda row: captured.__setitem__("row", row),
    )

    report_key = financial_report_usecase._persist_report_artifact(
        symbol="000333",
        report={
            "title": "2025年年度报告",
            "document_url": "https://example.com/report.pdf",
            "detail_url": "https://example.com/detail",
            "content_type": "application/pdf",
            "pdf_pages": 188,
        },
        report_text="annual report text",
        extracted_metrics={"revenue": 100.0},
        answers=[],
        llm_analysis=None,
    )

    cached = report_qa_service.get_cached_report_context(report_key)
    assert captured["row"]["report_key"] == report_key
    assert cached["report"]["document_url"] == "https://example.com/report.pdf"
    assert cached["extracted_metrics"]["revenue"] == 100.0
```

- [ ] **Step 2: Run the targeted usecase regression test**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_financial_report_usecase.py -k rehydrates_same_hot_context_shape`

Expected: PASS before the refactor or FAIL during rewiring until `_persist_report_artifact` uses the shared mapper

- [ ] **Step 3: Replace duplicate artifact/context conversion in the usecase**

In `app/usecases/financial_report_usecase.py`:

```python
from app.services.report_context_service import artifact_row_from_context
from app.services.report_context_service import build_report_key
from app.services.report_context_service import context_from_artifact_row


# delete _report_context_from_artifact_row(...)
# delete _artifact_row(...)

row = artifact_row_from_context(
    symbol=symbol,
    report=report,
    report_text=report_text,
    extracted_metrics=extracted_metrics,
    answers=answers,
    llm_analysis=llm_analysis,
    extraction_version=REPORT_EXTRACTION_VERSION,
    has_usable_report_metrics=_has_usable_report_metrics(extracted_metrics),
)

store_report_context(report_key, context_from_artifact_row(row))
```

Do not move these usecase-only helpers:
- `_artifact_has_current_extraction_version`
- `_artifact_is_eligible_for_autoread_reuse`
- `_restore_url_analysis_payload_from_artifact`
- `_restore_autoread_payload_from_artifact`

- [ ] **Step 4: Run usecase regressions**

Run: `.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_context_service.py tests/test_financial_report_usecase.py`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/usecases/financial_report_usecase.py tests/test_financial_report_usecase.py app/services/report_context_service.py tests/test_report_context_service.py
git commit -m "refactor(report): share artifact context mapping in usecase"
```

### Task 4: End-to-End Regression Sweep

**Files:**
- Verify only: `tests/test_financial_report_api.py`
- Verify only: `tests/test_report_qa_service.py`
- Verify only: `tests/test_financial_report_usecase.py`
- Verify only: `tests/test_report_context_service.py`

- [ ] **Step 1: Run the focused backend regression suite**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_report_context_service.py \
  tests/test_report_qa_service.py \
  tests/test_financial_report_usecase.py \
  tests/test_financial_report_api.py
```

Expected: PASS

- [ ] **Step 2: Smoke-check duplicate helpers are gone**

Run: `rg -n "_report_context_from_artifact_row|_context_from_artifact|def _artifact_row" app`

Expected: no matches in `app/usecases/financial_report_usecase.py` or `app/services/report_qa_service.py`

- [ ] **Step 3: Review import boundaries**

Run: `rg -n "build_report_key|context_from_artifact_row|artifact_row_from_context" app/usecases app/services`

Expected:
- shared conversion helpers live in `app/services/report_context_service.py`
- `report_qa_service.py` keeps cache functions
- `financial_report_usecase.py` keeps orchestration and parser-version checks

- [ ] **Step 4: Commit the verification checkpoint**

```bash
git add app/services/report_context_service.py app/services/report_qa_service.py app/usecases/financial_report_usecase.py tests/test_report_context_service.py tests/test_report_qa_service.py tests/test_financial_report_usecase.py
git commit -m "refactor(report): unify report artifact context boundaries"
```

## Notes

- Keep public behavior stable. This refactor is only about ownership of serialization logic.
- Do not change API payload field names.
- Do not move hot-cache storage out of `report_qa_service.py` in this slice.
- Do not refactor `report_snapshot` or LLM interpretation logic in this slice.
- If `tests/test_financial_report_api.py` fails, fix only import/behavior drift introduced by the shared mapper. Do not broaden scope.

## Self-Review

- Spec coverage: covers the duplicated mapper logic in `financial_report_usecase.py` and `report_qa_service.py`, plus regression coverage for persisted artifact reuse and Q&A cache reload.
- Placeholder scan: no `TODO`, `TBD`, or “write tests later” placeholders remain.
- Type consistency: the shared module owns `build_report_key`, `context_from_artifact_row`, and `artifact_row_from_context`; callers keep existing dictionary shapes.
