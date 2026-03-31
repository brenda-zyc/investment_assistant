# Structure Steering

## Source Layout

- `app/main.py`: FastAPI app factory and startup initialization.
- `app/api/`: route definitions and HTTP error mapping.
- `app/usecases/`: orchestration logic used by API routes.
- `app/services/`: external provider access, parsing, normalization, and resilience helpers.
- `app/db.py`: SQLite schema and persistence helpers.
- `tests/`: unit tests and service/usecase regression coverage.
- `scripts/`: operator scripts for macro indicator ingestion and similar tasks.

## Layering Rules

- API modules should stay thin. They validate inputs, call usecases, and map exceptions to HTTP responses.
- Usecases own workflow concerns such as deduplication, fan-out, fallback combination, and response shaping.
- Services handle provider-specific calls and normalization logic. Avoid putting route or database policy here.
- Persistence helpers should remain reusable and unaware of HTTP concerns.

## Change Guidelines

- Extend existing modules before creating new top-level packages unless a new boundary is clearly justified.
- Keep backward-compatible route payload shapes unless the spec explicitly allows a breaking change.
- Prefer pure helper extraction when adding non-trivial logic to usecases or services.
- Add or update tests in the narrowest layer that can verify the behavior deterministically.

## Current Hotspots

- `app/usecases/market_usecase.py`: watchlist orchestration, deduplication, and realtime merge behavior.
- `app/services/financial_report_service.py`: report extraction complexity and metric heuristics.
- `app/services/industry_data_service.py`: multi-source refresh resilience and diagnostics.
- `app/core_logic.py`: percentile/signal computation and derived scoring logic.
