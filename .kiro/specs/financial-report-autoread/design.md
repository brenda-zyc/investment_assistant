# Design

## Context

The repo already has a financial-report surface:

- `app/api/financial_report_api.py` exposes symbol- and URL-based report analysis routes.
- `app/usecases/financial_report_usecase.py` orchestrates symbol-based financial-summary analysis and URL parsing.
- `app/services/financial_report_service.py` fetches report URLs and extracts a small set of metrics from report text.
- `app/core_logic.py` computes report highlights from normalized financial rows.
- `app/templates/index.html` renders the report panel.

That existing flow is useful, but it does not yet provide the product behavior requested here:

- symbol -> auto-find latest annual report
- auto-read the report itself
- answer three specific business questions with evidence-backed output

## Goals

- Add a symbol-driven annual report auto-read workflow.
- Reuse existing report URL fetch and text parsing capabilities.
- Keep the new reasoning deterministic and explainable.
- Preserve graceful partial results when upstream network or extraction steps fail.

## Non-Goals

- Full OCR support for scanned PDF reports.
- Generic LLM orchestration across arbitrary report types.
- Replacing the existing `financial-report-analysis` endpoint.

## Proposed Architecture

### 1. Extend `financial_report_service.py` with report discovery and richer extraction

Add service helpers for:

- querying annual report disclosure entries by symbol
- selecting the latest full annual report candidate
- building a direct report document URL when a PDF attachment path is available
- extracting additional report metrics needed for the three questions

This keeps provider-specific disclosure lookup and text extraction logic in the service layer.

Expected new responsibilities:

- `find_latest_annual_report(symbol)`
- `extract_report_assessment_metrics(text, title=None)`

The disclosure source should follow the same upstream used by AkShare's official `stock_zh_a_disclosure_report_cninfo` interface and prefer a direct PDF URL when the disclosure payload exposes an attachment path.

### 2. Add deterministic assessment logic in `core_logic.py`

Create a pure analysis helper that converts extracted/latest metrics plus historical context into three structured answers.

Suggested entrypoint:

- `compute_financial_report_autoread_assessment(...)`

Inputs:

- latest report metrics extracted from report text
- normalized historical financial rows
- optional historical profit-quality metrics fetched from structured financial statement endpoints

Outputs:

- one result for each question:
  - `profit_authenticity`
  - `profit_sustainability`
  - `capital_intensity`

Each result should contain:

- `id`
- `question`
- `verdict`
- `level`
- `summary`
- `evidence`
- optional `score`

### 3. Use structured financial-statement history as a context enhancer

Add market-data service helpers to fetch richer historical fields from per-symbol Eastmoney financial-statement endpoints where available.

Suggested new helper in `app/services/market_data_service.py`:

- `fetch_report_assessment_context(symbol)`

Target metrics:

- net profit
- deducted net profit
- operating cash flow
- capex cash outflow
- revenue
- ROE when available

This helper should use tolerant column matching and return a compact normalized series dictionary rather than raw provider tables.

### 4. Add a dedicated usecase

Add a new workflow in `app/usecases/financial_report_usecase.py`:

- normalize symbol
- resolve symbol name when possible
- discover latest annual report
- fetch report content
- extract report metrics
- fetch historical context
- compute three-question assessment
- assemble warnings and source metadata

Suggested function:

- `autonomous_financial_report_read(symbol)`

The workflow should degrade in stages:

1. if report discovery fails, return warnings and no report metadata
2. if report content fetch fails, still try structured historical context
3. if historical context fails, still return report-only extraction analysis
4. if both fail, return explicit insufficient-data answers instead of a 500 when possible

### 5. Add a dedicated API route

Add a new route in `app/api/financial_report_api.py`:

- `GET /api/financial-report-autoread?symbol=XXXXXX`

The route remains thin:

- validate symbol
- call usecase
- map value/runtime/network exceptions to HTTP status codes

### 6. Add a new UI section inside the existing report panel

Update `app/templates/index.html` so the report panel can trigger and display the autonomous read result.

Recommended interaction:

- keep the existing `Load Reports` and `Analyze URL` actions
- add a third action such as `Auto Read Annual Report`
- render three assessment cards or rows beneath the current report summary

Each rendered item should show:

- question text
- verdict badge
- concise summary
- evidence bullets
- report source title/date/url when available

## Heuristic Design

### Profit authenticity

Primary evidence:

- operating cash flow vs net profit
- deducted net profit vs reported net profit

Interpretation bias:

- positive and well-covered cash flow improves confidence that profit is backed by cash
- a large gap between deducted and reported net profit weakens confidence
- missing both signals should produce an explicit insufficient-data verdict

### Profit sustainability

Primary evidence:

- multi-year revenue trend
- multi-year net-profit trend
- latest ROE
- latest operating cash flow and deducted-profit quality when available

Interpretation bias:

- stable or improving multi-year trends support sustainability
- declining profit with weak cash conversion should reduce confidence

### Capital intensity

Primary evidence:

- capex cash outflow vs revenue
- capex cash outflow vs operating cash flow

Interpretation bias:

- high capex ratios indicate the business needs heavier reinvestment to maintain or expand current operations
- if capex is unavailable, return an explicit limited-confidence verdict

## File Impact

- `app/services/financial_report_service.py`
  - annual report discovery
  - richer report metric extraction
- `app/services/market_data_service.py`
  - normalized context fetch for profit quality and capex fields
- `app/core_logic.py`
  - pure three-question assessment logic
- `app/usecases/financial_report_usecase.py`
  - new orchestration entrypoint
- `app/api/financial_report_api.py`
  - new endpoint
- `app/templates/index.html`
  - report-panel UI additions
- `tests/test_report_text_parser.py`
  - extraction/discovery helper coverage
- `tests/test_core_logic.py`
  - three-question scoring coverage
- optional `tests/test_financial_report_usecase.py`
  - usecase-level orchestration coverage if needed

## Risks And Mitigations

### Upstream disclosure lookup instability

Risk:

- report discovery depends on network-sensitive disclosure endpoints

Mitigation:

- return stable warnings and partial results
- keep the route schema stable even when discovery fails

### Report text is incomplete or PDF is image-based

Risk:

- some reports may not yield enough machine-readable text

Mitigation:

- reuse existing parser warnings
- allow structured financial-statement context to carry part of the analysis
- return explicit insufficient-data answers where needed

### Column-name variability in structured statement endpoints

Risk:

- Eastmoney financial-statement columns may vary across companies or upstream changes

Mitigation:

- use keyword-based column selection and normalized helper functions
- keep tests at the normalized-data layer with monkeypatched provider frames

## Validation Plan

- deterministic tests for report candidate selection
- deterministic tests for three-question scoring
- focused usecase tests with monkeypatched discovery/fetch/context helpers
- manual smoke check from the report panel using a known symbol such as `000333`
