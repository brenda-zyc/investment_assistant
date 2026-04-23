# Design: Version B Mainflow Stability

## Scope

Version B is the "make the current private research flows fast and stable" stage.

It does not add a full task runner yet. It does add the persistence and route boundaries that later make Version C possible.

## Goals

- make cached analyst-facing paths return quickly
- keep upstream refresh explicit and optional
- persist annual-report artifacts so report work survives process restarts
- move report Q&A onto persisted artifacts instead of process memory

## Non-Goals

- multi-user authentication
- a distributed job queue
- a generic portfolio workspace
- full LLM orchestration across stock, macro, and industry modules

## Main Decisions

### 1. Keep SQLite As The Version B Source Of Truth

Do not introduce a new storage system.

Version B extends `/Users/brenda/Projects/investment_assistant/app/db.py` with one new table for report artifacts and a few new helpers. This fits the current local-first single-user model and keeps the migration surface small.

### 2. Separate Read Paths From Refresh Paths

Current main-flow latency is dominated by synchronous upstream fetches inside request handling.

Version B changes the default request bias:

- read cached local data first
- refresh only when the caller explicitly asks
- preserve predictable fallback when refresh fails

This applies to:

- stock analysis
- watchlist analysis
- financial report summary
- annual-report auto-read

### 3. Persist Report Artifacts, Not Just Chat State

The biggest future blocker is not chat transcript storage. It is the lack of persisted parsed-report context.

Version B therefore stores reusable report artifacts:

- raw report text
- extracted metrics
- deterministic three-question answers
- optional last LLM notes
- source metadata

Q&A can then read the artifact by `report_key` even after a server restart.

## Modules

### Persistence

- `/Users/brenda/Projects/investment_assistant/app/db.py`
  - add `report_artifacts`
  - add artifact upsert/fetch helpers

### API

- `/Users/brenda/Projects/investment_assistant/app/api/market_api.py`
  - accept explicit refresh control for stock and watchlist requests
- `/Users/brenda/Projects/investment_assistant/app/api/financial_report_api.py`
  - accept explicit refresh control for report summary and auto-read
  - keep HTTP mapping thin

### Usecases

- `/Users/brenda/Projects/investment_assistant/app/usecases/market_usecase.py`
  - change stock/watchlist default path to cache-first
  - keep explicit refresh path available
- `/Users/brenda/Projects/investment_assistant/app/usecases/financial_report_usecase.py`
  - make financial-report summary cache-first
  - make auto-read artifact-aware
  - persist artifact after successful URL parse or auto-read

### Services

- `/Users/brenda/Projects/investment_assistant/app/services/report_qa_service.py`
  - resolve report context from SQLite-backed artifacts
  - keep any in-memory cache strictly optional, not authoritative
- `/Users/brenda/Projects/investment_assistant/app/services/financial_report_service.py`
  - no large architecture change; continue owning discovery, fetch, and parse logic

### Frontend

- `/Users/brenda/Projects/investment_assistant/app/templates/index.html`
  - keep default actions fast and local-first
  - add explicit refresh actions
  - show cached/refreshed artifact status
  - clarify "official disclosure links only" for report URL analysis

## Data Model

### `report_artifacts`

Suggested columns:

- `report_key TEXT PRIMARY KEY`
- `symbol TEXT NOT NULL`
- `document_url TEXT`
- `detail_url TEXT`
- `title TEXT`
- `published_at TEXT`
- `content_type TEXT`
- `pdf_pages INTEGER`
- `report_text TEXT NOT NULL`
- `extracted_metrics_json TEXT NOT NULL`
- `answers_json TEXT NOT NULL`
- `llm_analysis_json TEXT`
- `current_mode TEXT NOT NULL`
- `parsed_at TEXT NOT NULL`

The table is intentionally artifact-centric. It stores the reusable parsed report, not a user chat session.

## Request/Response Direction

### Stock / Watchlist

Default:

- read cache
- return snapshot quickly
- expose per-section status such as `cached`, `refreshed`, or `empty`

Explicit refresh:

- call upstream
- update SQLite
- fall back to existing cache on failure

### Financial Report Summary

Default:

- return cached financial summary rows

Explicit refresh:

- re-fetch upstream summary rows
- upsert cache
- return updated summary or cached fallback

### Auto Read

Default:

- if latest artifact for symbol exists, return it
- otherwise do discovery + fetch + parse and persist a new artifact

Explicit force refresh:

- re-run discovery + fetch + parse even if an artifact already exists

### Report URL Analysis

Default:

- if an artifact with the same `report_key` already exists, return it
- otherwise fetch/parse and persist it

## Failure Handling

- No cache and refresh fails:
  - return empty/stable payload with explicit warnings
- Cache exists and refresh fails:
  - return cache with warning
- Q&A requested after process restart:
  - succeed if artifact exists in SQLite
- Q&A requested for missing artifact:
  - return the existing validation failure

## Why This Is Version B Instead Of Version C

Version B deliberately stops before introducing:

- a job runner
- task queues
- shared LLM gateway for every module

It solves the highest-value current bottlenecks while creating one durable primitive for Version C:

- `report_artifacts` as reusable parsed-report storage
