Write or refine `.kiro/specs/<feature>/design.md` for the active feature.

Rules:

- Map the change to real modules and functions in this repo.
- Explain data flow, failure handling, and test strategy.
- Prefer incremental design that respects the current API/usecase/service/db boundaries.
- Call out risks when concurrency, caching, or upstream APIs are involved.
