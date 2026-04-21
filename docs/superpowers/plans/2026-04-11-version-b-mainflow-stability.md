# Version B Mainflow Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current private-research main flows fast and stable by switching stock/report reads to cache-first behavior, separating refresh from read actions, and persisting annual-report artifacts so Q&A and later batch work no longer depend on process memory.

**Architecture:** Keep FastAPI + SQLite as the only runtime stack. Usecases become explicit about `refresh` and `force_refresh` controls, while SQLite becomes the source of truth for reusable report artifacts. Report Q&A reads persisted artifacts by `report_key`, and the frontend treats "view cached data" and "refresh upstream data" as different actions.

**Tech Stack:** FastAPI, SQLite, plain HTML/JS frontend, AkShare, pypdf, pytest, standard-library concurrency

---

## File Map

**Create**
- `/Users/brenda/Projects/investment_assistant/.kiro/specs/version-b-mainflow-stability/requirements.md`
- `/Users/brenda/Projects/investment_assistant/.kiro/specs/version-b-mainflow-stability/design.md`
- `/Users/brenda/Projects/investment_assistant/.kiro/specs/version-b-mainflow-stability/tasks.md`

**Modify**
- `/Users/brenda/Projects/investment_assistant/app/db.py`
- `/Users/brenda/Projects/investment_assistant/app/api/market_api.py`
- `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
- `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py`
- `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`
- `/Users/brenda/Projects/investment_assistant/app/services/report_qa_service.py`
- `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
- `/Users/brenda/Projects/investment_assistant/tests/test_db.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_market_usecase.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_usecase.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_api.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_report_qa_service.py`
- `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`
- `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-04-11-version-b-cache-and-artifacts.md`
- `/Users/brenda/Projects/investment_assistant/docs/handoff.md`

## Implementation Notes Locked Before Coding

- Version B does **not** introduce Celery, Redis, or a distributed queue.
- `LLM session config` may remain process-memory based for now.
- `report_text`, extracted report metrics, deterministic answers, and optional last LLM notes shall move into SQLite-backed `report_artifacts`.
- Stock, watchlist, and report-summary routes default to cached reads. Refresh shall be explicit.
- `Auto Read Annual Report` defaults to reusing the latest stored artifact for the symbol unless the caller sets `force_refresh=true`.
- `Analyze Report URL` remains official-disclosure-only. The UI copy must say that plainly.

### Task 1: Add Report Artifact Persistence

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/db.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_db.py`

- [ ] **Step 1: Write the failing database tests**

```python
from __future__ import annotations

import sqlite3

from app import db


def test_init_db_creates_report_artifacts_table(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "investment.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    db.init_db()

    conn = sqlite3.connect(db_path)
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
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

    assert stored is not None
    assert stored["symbol"] == "000333"
    assert stored["extracted_metrics"]["revenue"] == 100.0
    assert stored["answers"][0]["id"] == "profit_authenticity"
```

- [ ] **Step 2: Run the focused tests to confirm they fail**

Run:

```bash
cd /Users/brenda/Projects/investment_assistant
source .venv/bin/activate
python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_db.py -k report_artifact
```

Expected:
- FAIL because `report_artifacts` helpers do not exist yet.

- [ ] **Step 3: Implement the SQLite schema and helpers**

Add a new table in `/Users/brenda/Projects/investment_assistant/app/db.py`:

```python
CREATE TABLE IF NOT EXISTS report_artifacts (
    report_key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    document_url TEXT,
    detail_url TEXT,
    title TEXT,
    published_at TEXT,
    content_type TEXT,
    pdf_pages INTEGER,
    report_text TEXT NOT NULL,
    extracted_metrics_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    llm_analysis_json TEXT,
    current_mode TEXT NOT NULL,
    parsed_at TEXT NOT NULL
)
```

Add helpers with stable signatures:

```python
def upsert_report_artifact(row: dict[str, Any]) -> None: ...

def fetch_report_artifact(report_key: str) -> dict[str, Any] | None: ...

def fetch_latest_report_artifact_for_symbol(symbol: str) -> dict[str, Any] | None: ...
```

Store structured fields as JSON text on write and decode them on read.

- [ ] **Step 4: Run the focused tests again**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_db.py -k report_artifact
```

Expected:
- PASS for the new schema and round-trip behavior.

- [ ] **Step 5: Commit the persistence foundation**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add persisted report artifacts"
```

### Task 2: Make Stock And Report Summary Reads Cache-First

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/api/market_api.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_market_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_api.py`

- [ ] **Step 1: Write failing usecase tests for cache-first behavior**

```python
def test_analyze_single_symbol_uses_cache_without_network_when_refresh_false(monkeypatch) -> None:
    monkeypatch.setattr(market_usecase, "fetch_stock_prices", lambda symbol: [{"trade_date": "2026-04-09", "close": 10.0}])
    monkeypatch.setattr(market_usecase, "fetch_financial_reports", lambda symbol: [{"report_year": 2025, "report_date": "2025-12-31"}])

    def fail_price_fetch(_symbol: str):
        raise AssertionError("network fetch should not run")

    def fail_financial_fetch(_symbol: str):
        raise AssertionError("network fetch should not run")

    monkeypatch.setattr(market_usecase, "fetch_price_data", fail_price_fetch)
    monkeypatch.setattr(market_usecase, "fetch_financial_summary", fail_financial_fetch)

    payload = market_usecase.analyze_single_symbol("000333", refresh=False)

    assert payload["price_data"]
    assert payload["financial_summary"]
```

```python
def test_get_financial_report_analysis_uses_cache_without_upstream_when_refresh_false(monkeypatch) -> None:
    monkeypatch.setattr(financial_report_usecase, "fetch_financial_reports", lambda symbol: [{"report_year": 2025, "report_date": "2025-12-31", "revenue": 1.0}])

    def fail_fetch(_symbol: str):
        raise AssertionError("financial upstream fetch should not run")

    monkeypatch.setattr(financial_report_usecase, "fetch_financial_summary", fail_fetch)

    payload = financial_report_usecase.get_financial_report_analysis("000333", refresh=False)

    assert payload["series"]
```

- [ ] **Step 2: Run focused tests to confirm failures**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_market_usecase.py \
  tests/test_financial_report_usecase.py \
  tests/test_financial_report_api.py -k 'cache_first or refresh'
```

Expected:
- FAIL because the current usecases fetch upstream before using cache.

- [ ] **Step 3: Refactor usecases to make refresh explicit**

In `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py`, evolve the signatures toward:

```python
def analyze_single_symbol(symbol: str, *, refresh: bool = False) -> dict: ...

def analyze_multi_symbols(raw_codes: list[str], *, refresh: bool = False) -> dict: ...
```

Refactor `_fetch_cached_symbol_data(...)` into a helper that:

- reads local cache first
- refreshes upstream only when `refresh=True` or local cache is missing
- returns section-level status metadata such as `cached`, `refreshed`, or `empty`

In `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`, evolve:

```python
def get_financial_report_analysis(symbol: str, *, refresh: bool = False) -> dict: ...
```

Use the same rule:

- cached rows first
- upstream refresh only when requested or cache is empty

- [ ] **Step 4: Extend the API contracts without breaking callers**

Update request shapes:

```python
class AnalyzeRequest(BaseModel):
    stock_code: str
    refresh: bool = False


class MultiAnalyzeRequest(BaseModel):
    stock_codes: list[str]
    refresh: bool = False
```

Add `refresh: bool = Query(default=False)` to `financial_report_analysis(...)`.

Old callers that do not send `refresh` shall keep working.

- [ ] **Step 5: Re-run focused tests**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_market_usecase.py \
  tests/test_financial_report_usecase.py \
  tests/test_financial_report_api.py
```

Expected:
- PASS with new cache-first behavior and compatible request validation.

- [ ] **Step 6: Commit the cache-first read path**

```bash
git add app/usecases/market_usecase.py app/usecases/financial_report_usecase.py app/api/market_api.py app/api/financial_report_api.py tests/test_market_usecase.py tests/test_financial_report_usecase.py tests/test_financial_report_api.py
git commit -m "feat: make stock and report reads cache-first"
```

### Task 3: Persist Auto-Read Results And Move Q&A To Artifact Storage

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/services/report_qa_service.py`
- Modify: `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_usecase.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_report_qa_service.py`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_api.py`

- [ ] **Step 1: Write failing tests for artifact reuse**

```python
def test_financial_report_autoread_reuses_latest_artifact_when_force_refresh_false(monkeypatch) -> None:
    monkeypatch.setattr(
        financial_report_usecase,
        "fetch_latest_report_artifact_for_symbol",
        lambda symbol: {
            "report_key": "000333|https://static.cninfo.com.cn/report.pdf",
            "symbol": "000333",
            "title": "2025年年度报告",
            "report_text": "cached report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [{"id": "profit_authenticity", "summary": "cached"}],
            "llm_analysis": None,
            "current_mode": "report_text_extracted",
            "parsed_at": "2026-04-11T15:00:00",
        },
    )

    def fail_discovery(_symbol: str):
        raise AssertionError("report discovery should not run")

    monkeypatch.setattr(financial_report_usecase, "find_latest_annual_report", fail_discovery)

    payload = financial_report_usecase.autonomous_financial_report_read("000333", force_refresh=False)

    assert payload["report_key"] == "000333|https://static.cninfo.com.cn/report.pdf"
    assert payload["answers"][0]["summary"] == "cached"
```

```python
def test_answer_report_question_loads_persisted_artifact_when_memory_cache_is_empty(monkeypatch) -> None:
    report_qa_service.clear_report_context_cache()
    monkeypatch.setattr(
        report_qa_service,
        "fetch_report_artifact",
        lambda report_key: {
            "report_key": report_key,
            "symbol": "000333",
            "report_text": "annual report text",
            "extracted_metrics": {"revenue": 100.0},
            "answers": [],
            "llm_analysis": None,
            "report": {"title": "2025年年度报告"},
        },
    )

    payload = report_qa_service.answer_report_question(
        symbol="000333",
        report_key="000333|https://static.cninfo.com.cn/report.pdf",
        question="收入怎么样？",
        history=[],
        session_summary="",
        use_llm=False,
    )

    assert payload["report_key"] == "000333|https://static.cninfo.com.cn/report.pdf"
```

- [ ] **Step 2: Run focused tests to confirm failures**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_financial_report_usecase.py \
  tests/test_report_qa_service.py \
  tests/test_financial_report_api.py -k 'artifact or force_refresh or persisted'
```

Expected:
- FAIL because auto-read and Q&A do not use SQLite-backed artifacts yet.

- [ ] **Step 3: Refactor auto-read and URL analysis to persist artifacts**

In `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`, add helpers shaped like:

```python
def _artifact_row_from_autoread_payload(...) -> dict: ...

def _artifact_row_from_url_analysis(...) -> dict: ...

def _restore_payload_from_artifact(row: dict) -> dict: ...
```

Update:

```python
def autonomous_financial_report_read(symbol: str, *, force_refresh: bool = False) -> dict: ...

def analyze_financial_report_url(url: str, symbol: str | None = None, *, force_refresh: bool = False) -> dict: ...
```

Behavior:

- reuse the latest artifact when not forcing refresh
- persist a new artifact after a successful fetch/parse
- expose artifact freshness metadata in the returned payload

- [ ] **Step 4: Make Q&A use SQLite-backed artifacts as the authoritative source**

In `/Users/brenda/Projects/investment_assistant/app/services/report_qa_service.py`:

- keep `_REPORT_CONTEXTS` only as an optional hot cache if desired
- on a cache miss, call `fetch_report_artifact(report_key)`
- reconstruct the same context shape expected by the existing Q&A logic
- reject only when neither memory nor SQLite has the artifact

- [ ] **Step 5: Extend route contracts for force refresh**

In `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`:

- add `force_refresh: bool = Query(default=False)` to `financial_report_autoread(...)`
- add `force_refresh: bool = False` to `FinancialReportUrlRequest`
- pass the flag through to the usecase layer

- [ ] **Step 6: Re-run focused tests**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_financial_report_usecase.py \
  tests/test_report_qa_service.py \
  tests/test_financial_report_api.py
```

Expected:
- PASS for artifact reuse, persisted-context Q&A, and force-refresh wiring.

- [ ] **Step 7: Commit the artifact-backed report flow**

```bash
git add app/usecases/financial_report_usecase.py app/services/report_qa_service.py app/api/financial_report_api.py tests/test_financial_report_usecase.py tests/test_report_qa_service.py tests/test_financial_report_api.py
git commit -m "feat: persist report artifacts and reuse them in qa"
```

### Task 4: Update The Frontend For Explicit Refresh And Artifact Status

**Files:**
- Modify: `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
- Modify: `/Users/brenda/Projects/investment_assistant/tests/test_financial_report_frontend.py`

- [ ] **Step 1: Write failing frontend tests for refresh wiring and copy**

Add source-level checks such as:

```python
def test_stock_panel_exposes_explicit_refresh_controls() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'id="refreshSingleStockBtn"' in source
    assert 'id="refreshWatchlistBtn"' in source


def test_report_panel_marks_url_analysis_as_official_disclosure_only() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "official disclosure" in source.lower()


def test_auto_read_supports_force_refresh_request_flag() -> None:
    source = TEMPLATE_PATH.read_text(encoding="utf-8")
    body = _function_body(source, "async function autoReadAnnualReport(forceRefresh = false)")
    assert "force_refresh=" in body
```

- [ ] **Step 2: Run the focused frontend tests to confirm failures**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_financial_report_frontend.py -k 'refresh or official'
```

Expected:
- FAIL because the current template does not separate cached reads from refresh actions clearly enough.

- [ ] **Step 3: Implement explicit read-vs-refresh UI**

In `/Users/brenda/Projects/investment_assistant/app/templates/index.html`:

- keep the existing default load/analyze actions as cache-first
- add explicit refresh buttons for:
  - single stock
  - watchlist
  - financial report summary
  - optional force re-read of annual report
- update status text to surface `cached`, `refreshed`, or `artifact reused`
- update report URL helper copy to say "official disclosure links only"

Wire the JS calls so refresh buttons send:

```javascript
body: JSON.stringify({ stock_code: code, refresh: true })
```

and:

```javascript
`${apiBase}/api/financial-report-autoread?symbol=${encodeURIComponent(code)}&force_refresh=true`
```

- [ ] **Step 4: Re-run the focused frontend tests**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' tests/test_financial_report_frontend.py
```

Expected:
- PASS with explicit refresh wiring and clarified copy.

- [ ] **Step 5: Commit the UI clarity pass**

```bash
git add app/templates/index.html tests/test_financial_report_frontend.py
git commit -m "feat: separate cached reads from refresh actions in ui"
```

### Task 5: Verification, Decision Log, And Handoff

**Files:**
- Create: `/Users/brenda/Projects/investment_assistant/docs/decisions/2026-04-11-version-b-cache-and-artifacts.md`
- Modify: `/Users/brenda/Projects/investment_assistant/docs/handoff.md`

- [ ] **Step 1: Record the architecture decision**

Write a decision note that captures:

- cache-first default path for analyst-facing requests
- explicit refresh controls
- SQLite-backed `report_artifacts`
- process memory no longer being the only report-context source

- [ ] **Step 2: Run focused regression suites**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_db.py \
  tests/test_market_usecase.py \
  tests/test_financial_report_usecase.py \
  tests/test_financial_report_api.py \
  tests/test_report_qa_service.py \
  tests/test_financial_report_frontend.py
```

Expected:
- PASS for Version B surfaces.

- [ ] **Step 3: Run the stable full-suite regression**

Run:

```bash
python3 -m pytest -p no:cov -q --override-ini addopts=''
```

Expected:
- PASS for the full repo suite.

- [ ] **Step 4: Run compile verification**

Run:

```bash
python3 -m compileall /Users/brenda/Projects/investment_assistant/app
```

Expected:
- compile completes without syntax errors.

- [ ] **Step 5: Manual smoke pass**

Run the app and validate:

- `000333` single-stock cached load returns quickly
- explicit stock refresh still works
- watchlist cached load returns rows in order
- report summary loads from cache
- auto-read reuses artifact on repeated call
- force-refresh re-parses when requested
- Q&A still works after restarting the server because SQLite artifact exists

- [ ] **Step 6: Update handoff**

Capture:

- cache-first route behavior
- explicit refresh actions
- `report_artifacts` storage semantics
- remaining gaps reserved for Version C

- [ ] **Step 7: Final commit**

```bash
git add docs/decisions/2026-04-11-version-b-cache-and-artifacts.md docs/handoff.md
git commit -m "docs: record version b cache and artifact design"
```

## Version C Hook

After Version B is complete, Version C can build on:

- `report_artifacts` as reusable parsed-report storage
- explicit `refresh` / `force_refresh` route controls
- artifact-backed Q&A

That is the point where introducing a lightweight task/job model and a shared LLM gateway becomes worthwhile.
