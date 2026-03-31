# Requirements

## Summary

Add an autonomous annual-report reading workflow that can take a 6-digit A-share symbol, locate the latest annual report announcement, extract report content, and answer three investor-facing questions with evidence-backed outputs:

1. Is the company's net profit likely real?
2. Is the net profit likely sustainable?
3. Does maintaining the current business state require heavy capital investment?

## Functional Requirements

### FR-1 Symbol-Based Annual Report Discovery

When the user submits a stock symbol for autonomous report reading, the system shall attempt to find the latest full annual report announcement for that company.

Acceptance criteria:

- The workflow shall query a report-disclosure source by stock symbol.
- The workflow shall prefer full annual reports over summaries, English versions, or unrelated disclosures when multiple candidates exist.
- The workflow shall return report metadata including title, announcement date, and source URL when discovery succeeds.
- If discovery fails, the workflow shall return a predictable payload with warnings instead of crashing.

### FR-2 Report Content Retrieval And Extraction

After finding a report, the system shall retrieve report content and extract core metrics needed for the three-question assessment.

Acceptance criteria:

- The workflow shall support report URLs that resolve to HTML or PDF content.
- The workflow shall attempt to extract at least the following report-level metrics when available:
  - revenue
  - net profit
  - deducted net profit
  - operating cash flow
  - ROE
  - debt ratio
  - capex cash outflow
- The workflow shall surface extraction warnings when one or more metrics cannot be extracted reliably.

### FR-3 Three-Question Assessment

The system shall answer the three target questions using deterministic logic and explicit evidence.

Acceptance criteria:

- The output shall contain one structured result per question.
- Each result shall contain:
  - stable question identifier
  - question text
  - verdict label
  - severity level or color-compatible state
  - concise explanation
  - evidence list
- The system shall compute answers from available report metrics and historical financial context.
- When data is insufficient, the verdict shall be explicit rather than silently omitted.

### FR-4 Historical Context For Sustainability And Capital Intensity

The system shall use historical financial context where available instead of judging only from a single latest report.

Acceptance criteria:

- The sustainability assessment shall consider multi-year revenue and net-profit history when available.
- The authenticity assessment shall consider operating cash flow and deducted net profit when available.
- The capital-intensity assessment shall consider capex-related metrics when available.
- Historical fetch failures shall degrade gracefully to partial analysis with warnings.

### FR-5 API Integration

The backend shall expose a dedicated endpoint for autonomous annual-report reading.

Acceptance criteria:

- The endpoint shall accept a 6-digit symbol.
- The endpoint shall return a predictable JSON payload containing:
  - symbol
  - symbol name when available
  - discovered report metadata
  - extracted report metrics
  - three-question assessment
  - warnings
- Input validation and HTTP exception mapping shall remain in the API layer.

### FR-6 UI Integration

The frontend shall allow the user to trigger the new workflow from the existing report-analysis area.

Acceptance criteria:

- The report panel shall expose a clear symbol-driven action for autonomous report reading.
- The page shall render the three answers in a readable format without replacing the existing financial-report tools.
- The page shall show warnings and source metadata when discovery or extraction falls back or partially fails.

## Non-Functional Requirements

### NFR-1 Graceful Partial Results

The feature shall prefer partial analysis over all-or-nothing failure.

Acceptance criteria:

- Report discovery, report parsing, and historical context fetches shall fail independently where possible.
- The response shall preserve a stable schema even when some sub-steps fail.

### NFR-2 Testability

Core logic for discovery selection and three-question scoring shall be covered by deterministic tests.

Acceptance criteria:

- Tests shall not depend on live upstream network access.
- Tests shall cover at least one positive case and one insufficient-data case for the assessment logic.
