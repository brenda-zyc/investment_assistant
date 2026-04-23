# Requirements: Version B Mainflow Stability

## Summary

Version B shall make the existing private-research workflows faster and more stable without turning the app into a full task platform yet.

The scope focuses on:

- cache-first read paths for current main flows
- explicit separation between reading cached data and refreshing upstream data
- persisted annual-report artifacts so report reuse and later batch workflows do not depend on process memory
- predictable freshness and fallback signals in API responses and the single-page UI

## Functional Requirements

### FR-1 Cache-First Stock Analysis

The stock-analysis workflows shall return cached results before attempting slow upstream refreshes.

Acceptance criteria:

- `POST /api/analyze` shall use cached `stock_prices` and `financial_reports` when they already exist and the request does not explicitly ask for refresh.
- `POST /api/analyze-multi` shall keep order preservation, deduplication, and partial-failure isolation while defaulting to cached snapshots.
- The response shall expose enough metadata for the frontend to distinguish cached vs refreshed data.

### FR-2 Explicit Refresh Semantics

The system shall separate "show me what I already have" from "go fetch newer data".

Acceptance criteria:

- Stock-analysis and financial-report-summary routes shall accept an explicit refresh control instead of always fetching upstream data first.
- The UI shall expose a clear refresh action for stock and report workflows.
- A refresh failure shall still return cached data when compatible cache exists.

### FR-3 Persisted Report Artifacts

The system shall persist reusable annual-report artifacts in SQLite.

Acceptance criteria:

- A new persistence shape shall store at least:
  - `report_key`
  - `symbol`
  - `document_url`
  - `detail_url`
  - `title`
  - `published_at`
  - `content_type`
  - `pdf_pages`
  - `report_text`
  - `extracted_metrics`
  - `answers`
  - `current_mode`
  - `llm_analysis` when available
  - `parsed_at`
- `Auto Read Annual Report` and `Analyze Report URL` shall write reusable artifacts after a successful parse.
- The same report shall be reusable after a process restart.

### FR-4 Artifact-Backed Report Q&A

Report Q&A shall stop depending on in-process report context as the only source of truth.

Acceptance criteria:

- Q&A shall resolve report context from persisted artifacts by `report_key`.
- Missing in-memory cache shall not break Q&A if the artifact exists in SQLite.
- Requests with mismatched `symbol` and `report_key` shall still be rejected.

### FR-5 Cache Reuse For Auto-Read

The annual-report auto-read flow shall reuse the latest compatible artifact when the user is not forcing a re-read.

Acceptance criteria:

- `GET /api/financial-report-autoread` shall return the latest stored artifact for the requested symbol when `force_refresh=false` and a compatible artifact exists.
- The route shall still support an explicit force-refresh path for re-discovery and re-parse.
- The response shall expose whether the result came from a reused artifact or a fresh parse.

### FR-6 Official-Source URL Clarity

The report-URL workflow shall match the current official-disclosure-only constraint explicitly.

Acceptance criteria:

- The Financial Reports UI shall state that URL analysis supports official disclosure links only.
- URL validation failures shall stay clear and operator-readable.

## Non-Functional Requirements

### NFR-1 Latency Bias

The default analyst-facing path shall prefer bounded local reads over waiting on unstable upstream APIs.

Acceptance criteria:

- Cached single-stock and cached report-summary requests shall no longer require a successful upstream round-trip before returning data.
- Upstream timeout and DNS failures shall degrade quickly into cached fallback or explicit warnings.

### NFR-2 Batch Readiness

The Version B design shall leave a clean path toward later batch workflows.

Acceptance criteria:

- Persisted report artifacts shall be reusable by later batch jobs without needing frontend-owned state.
- Version B shall not require introducing Celery, Redis, or a distributed queue.

### NFR-3 Deterministic Testing

The new behavior shall be covered without live network access.

Acceptance criteria:

- Tests shall cover cache-first behavior, refresh gating, report-artifact round-trips, artifact-backed Q&A, and UI refresh wiring.
- Existing response-shape guarantees shall remain backward-compatible for callers that ignore the new metadata fields.
