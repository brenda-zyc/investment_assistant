# Report QA Dialogue Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add end-to-end dialogue regressions for report Q&A and implement `out_of_report_llm` so out-of-scope turns can use general LLM answers without polluting report-session memory.

**Architecture:** Keep all coverage in `tests/test_report_qa_service.py` as dialogue-style scripts built around a small test-local helper. Extend `app/services/report_qa_service.py` only where needed to support the new product boundary: report-scoped turns keep the existing report flow, while out-of-scope turns switch to `out_of_report_llm` and preserve report-session continuity.

**Tech Stack:** Python, pytest, FastAPI service layer, monkeypatch-based LLM fakes

---

## File Structure

- Modify: `app/services/report_qa_service.py`
  - add the smallest production logic needed for `out_of_report_llm`
  - keep report-scoped flow unchanged unless a regression proves otherwise
  - ensure out-of-report turns do not mutate report-session summary state
- Modify: `tests/test_report_qa_service.py`
  - add one test-local `ask_and_append(...)` helper
  - add four dialogue-style regression tests
  - keep existing single-behavior tests intact

## Task 1: Add Dialogue Test Harness And Rule-Only Regression

**Files:**
- Modify: `tests/test_report_qa_service.py`
- Test: `tests/test_report_qa_service.py`

- [ ] **Step 1: Write the failing helper-backed dialogue test**

Add a new dialogue test that uses a not-yet-defined local helper so the test fails immediately and proves the harness is not already present.

```python
def test_report_qa_rule_only_dialogue_flow() -> None:
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        "600519|rule-dialogue",
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": "https://example.com/rule-dialogue.pdf"},
            "report_text": (
                "营业收入变动原因说明：主要是本期销量增加及茅台酒主要产品销售价格调整。 "
                "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"
            ),
            "answers": [
                {
                    "question": "这家企业净利润是否为真？",
                    "summary": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "revenue": 170899152276.34,
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )

    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(
        history,
        "扣非净利润和净利润分别为多少？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )
    q2, session_summary = ask_and_append(
        history,
        "为什么你认为净利润较为真实？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )
    q3, session_summary = ask_and_append(
        history,
        "今年利润增长主要来自哪里？",
        session_summary=session_summary,
        symbol="600519",
        report_key="600519|rule-dialogue",
        use_llm=False,
    )

    assert q1["mode"] == "rule_fallback"
    assert "扣非净利润约862.41亿元" in q1["short_answer"]
    assert "净利润约862.28亿元" in q1["short_answer"]
    assert q2["mode"] == "rule_fallback"
    assert "经营现金流" in q2["short_answer"]
    assert "扣非净利润" in q2["short_answer"]
    assert q3["mode"] == "rule_fallback"
    assert "销量增加" in q3["short_answer"]
    assert "价格调整" in q3["short_answer"]
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py::test_report_qa_rule_only_dialogue_flow
```

Expected:

- `FAIL`
- error mentions `ask_and_append` is not defined

- [ ] **Step 3: Add the minimal local dialogue helper**

Add this helper near the other report-QA test utilities in `tests/test_report_qa_service.py`.

```python
def ask_and_append(
    history: list[dict[str, object]],
    question: str,
    *,
    session_summary: str,
    symbol: str,
    report_key: str,
    use_llm: bool,
) -> tuple[dict[str, object], str]:
    payload = report_qa_service.answer_report_question(
        symbol=symbol,
        report_key=report_key,
        question=question,
        history=cast(list[dict[str, Any]], history),
        session_summary=session_summary,
        use_llm=use_llm,
    )
    history.append({"role": "user", "content": question})
    history.append(
        {
            "role": "assistant",
            "content": payload["short_answer"],
            "evidence": payload.get("evidence", []),
            "citations": payload.get("citations", []),
            "mode": payload.get("mode"),
        }
    )
    return payload, str(payload.get("updated_session_summary") or session_summary)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py::test_report_qa_rule_only_dialogue_flow
```

Expected:

- `PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_qa_service.py
git commit -m "test(report): add rule-only dialogue regression"
```

## Task 2: Add Hybrid Dialogue And Follow-Up Dialogue Regressions

**Files:**
- Modify: `tests/test_report_qa_service.py`
- Test: `tests/test_report_qa_service.py`

- [ ] **Step 1: Write the failing hybrid and follow-up dialogue tests**

Add two new dialogue tests.

```python
def test_report_qa_llm_hybrid_dialogue_flow(monkeypatch) -> None:
    responses = iter(
        [
            {
                "short_answer": "扣非净利润为862.41亿元，净利润为862.28亿元。",
                "evidence": [
                    "扣非净利润与净利润口径接近。",
                    "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                ],
                "citations": [
                    {
                        "source": "report_text",
                        "snippet": "归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38 62,717,467,870.12",
                    }
                ],
                "confidence": "high",
            },
            {
                "short_answer": "净利润较为真实，主要因为经营现金流与净利润匹配度高，且扣非净利润与净利润基本一致。",
                "evidence": [
                    "经营现金流/净利润 = 1.07x。",
                    "扣非净利润/净利润 = 1.00x。",
                ],
                "citations": [
                    {"source": "report_text", "snippet": "经营活动产生的现金流量净额92,463,692,168.43元。"},
                    {"source": "report_text", "snippet": "归属于上市公司股东的净利润86,228,146,421.62元。"},
                ],
                "confidence": "high",
            },
            {},
        ]
    )

    monkeypatch.setattr(report_qa_service, "answer_report_question_with_llm", lambda **_: next(responses))

    history: list[dict[str, object]] = []
    session_summary = ""
    q1, session_summary = ask_and_append(history, "扣非净利润和净利润分别为多少？", session_summary=session_summary, symbol="600519", report_key="600519|hybrid-dialogue", use_llm=True)
    q2, session_summary = ask_and_append(history, "为什么你认为净利润较为真实？", session_summary=session_summary, symbol="600519", report_key="600519|hybrid-dialogue", use_llm=True)
    q3, session_summary = ask_and_append(history, "今年利润增长主要来自哪里？", session_summary=session_summary, symbol="600519", report_key="600519|hybrid-dialogue", use_llm=True)

    assert q1["mode"] == "llm_hybrid"
    assert q1["citations"]
    assert q2["mode"] == "llm_hybrid"
    assert q2["evidence"] == []
    assert q3["mode"] == "rule_fallback"
    assert "销量增加" in q3["short_answer"]


def test_report_qa_follow_up_dialogue_flow() -> None:
    history: list[dict[str, object]] = []
    session_summary = ""

    q1, session_summary = ask_and_append(history, "经营现金流和净利润匹配吗？", session_summary=session_summary, symbol="600519", report_key="600519|follow-up-dialogue", use_llm=False)
    q2, session_summary = ask_and_append(history, "为什么这么说？", session_summary=session_summary, symbol="600519", report_key="600519|follow-up-dialogue", use_llm=False)
    q3, session_summary = ask_and_append(history, "也没有展开呀", session_summary=session_summary, symbol="600519", report_key="600519|follow-up-dialogue", use_llm=False)
    q4, session_summary = ask_and_append(history, "展开一点", session_summary=session_summary, symbol="600519", report_key="600519|follow-up-dialogue", use_llm=False)

    assert q1["mode"] == "rule_fallback"
    assert q2["mode"] in {"rule_fallback", "llm_hybrid"}
    assert q3["mode"] in {"rule_fallback", "llm_hybrid"}
    assert q4["mode"] == "clarification"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_report_qa_service.py::test_report_qa_llm_hybrid_dialogue_flow \
  tests/test_report_qa_service.py::test_report_qa_follow_up_dialogue_flow
```

Expected:

- at least one `FAIL`
- failure should be on dialogue behavior, not import errors

- [ ] **Step 3: Make the smallest test-only adjustments needed**

If the tests fail because the shared context fixture is duplicated or missing, extract one test-local fixture builder in `tests/test_report_qa_service.py` and use it in all dialogue tests.

```python
def store_dialogue_context(report_key: str) -> None:
    report_qa_service.clear_report_context_cache()
    report_qa_service.store_report_context(
        report_key,
        {
            "symbol": "600519",
            "report": {"title": "贵州茅台2024年年度报告", "document_url": f"https://example.com/{report_key}.pdf"},
            "report_text": (
                "营业收入变动原因说明：主要是本期销量增加及茅台酒主要产品销售价格调整。 "
                "经营活动产生的现金流量净额变动原因说明：主要是本期公司销售商品收到的现金增加。"
            ),
            "answers": [
                {
                    "question": "这家企业净利润是否为真？",
                    "summary": "利润与现金流、扣非口径的偏离不大，利润质量整体较好。",
                    "evidence": ["经营现金流/净利润 = 1.07x。", "扣非净利润/净利润 = 1.00x。"],
                }
            ],
            "llm_analysis": None,
            "extracted_metrics": {
                "report_year": 2024,
                "report_date": "2024-12-31",
                "revenue": 170899152276.34,
                "net_profit": 86228146421.62,
                "deducted_net_profit": 86240905977.42,
                "operating_cash_flow": 92463692168.43,
            },
        },
    )
```

- [ ] **Step 4: Run the two tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_report_qa_service.py::test_report_qa_llm_hybrid_dialogue_flow \
  tests/test_report_qa_service.py::test_report_qa_follow_up_dialogue_flow
```

Expected:

- `PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_qa_service.py
git commit -m "test(report): add dialogue regressions for hybrid and follow-up flows"
```

## Task 3: Implement Out-Of-Report LLM Mode And Scope-Boundary Regression

**Files:**
- Modify: `app/services/report_qa_service.py`
- Modify: `tests/test_report_qa_service.py`
- Test: `tests/test_report_qa_service.py`

- [ ] **Step 1: Write the failing scope-boundary regression**

Add the new end-to-end scope-boundary dialogue test.

```python
def test_report_qa_scope_boundary_dialogue_flow(monkeypatch) -> None:
    out_of_scope_responses = iter(
        [
            {"short_answer": "估值是否偏贵要结合当前价格、增长预期和市场风险偏好综合判断。"},
            {"short_answer": "行业景气度需要看需求、价格和库存周期，不能只靠年报单点判断。"},
        ]
    )

    def fake_general_llm(**kwargs):
        return next(out_of_scope_responses)

    monkeypatch.setattr(report_qa_service, "answer_general_question_with_llm", fake_general_llm)

    history: list[dict[str, object]] = []
    session_summary = ""
    q1, session_summary = ask_and_append(history, "净利润是否为真？", session_summary=session_summary, symbol="600519", report_key="600519|scope-dialogue", use_llm=False)
    q2, session_summary = ask_and_append(history, "那现在估值贵不贵？", session_summary=session_summary, symbol="600519", report_key="600519|scope-dialogue", use_llm=True)
    q3, session_summary = ask_and_append(history, "行业景气度怎么样？", session_summary=session_summary, symbol="600519", report_key="600519|scope-dialogue", use_llm=True)
    q4, session_summary = ask_and_append(history, "为什么你这么判断净利润？", session_summary=session_summary, symbol="600519", report_key="600519|scope-dialogue", use_llm=False)

    assert q1["mode"] in {"rule_fallback", "llm_hybrid"}
    assert q2["mode"] == "out_of_report_llm"
    assert q3["mode"] == "out_of_report_llm"
    assert q2["updated_session_summary"] == q1["updated_session_summary"]
    assert q3["updated_session_summary"] == q1["updated_session_summary"]
    assert q4["mode"] in {"rule_fallback", "llm_hybrid"}
    assert "净利润" in q4["short_answer"]
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py::test_report_qa_scope_boundary_dialogue_flow
```

Expected:

- `FAIL`
- current behavior should return `rule_fallback` for the out-of-scope turns because `out_of_report_llm` does not exist yet

- [ ] **Step 3: Add minimal production support for `out_of_report_llm`**

In `app/services/report_qa_service.py`, add one small wrapper plus one branch inside `answer_report_question(...)`.

```python
def answer_general_question_with_llm(*, question: str, history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a general LLM answer for out-of-report turns without using report-grounded evidence semantics."""
    response = llm_service.answer_general_question(question=question, history=history)
    if not isinstance(response, dict):
        return None

    short_answer = str(response.get("short_answer") or response.get("answer") or "").strip()
    if not short_answer:
        return None

    return {
        "mode": "out_of_report_llm",
        "short_answer": short_answer,
        "evidence": [],
        "citations": [],
        "confidence": str(response.get("confidence") or "low").strip() or "low",
    }
```

Then replace the current out-of-scope branch in `answer_report_question(...)` with:

```python
    if not is_report_scoped:
        if use_llm:
            general_answer = answer_general_question_with_llm(
                question=question_text,
                history=bounded_history,
            )
            if general_answer is not None:
                general_answer["updated_session_summary"] = session_summary
                general_answer["session_reset"] = False
                general_answer["report_key"] = report_key
                return general_answer

        fallback = build_rule_fallback_answer_with_scope(
            llm_question,
            context,
            allow_cached_answer=False,
            history=bounded_history,
        )
        fallback["updated_session_summary"] = session_summary
        fallback["session_reset"] = False
        fallback["report_key"] = report_key
        return fallback
```

This is intentionally minimal:

- scope-out turns use general LLM only when `use_llm=True`
- summary preservation uses the incoming `session_summary`, not `updated_summary`
- report-grounded fallback remains the backup when the general LLM returns nothing usable

- [ ] **Step 4: Run the scope-boundary test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py::test_report_qa_scope_boundary_dialogue_flow
```

Expected:

- `PASS`

- [ ] **Step 5: Commit**

```bash
git add app/services/report_qa_service.py tests/test_report_qa_service.py
git commit -m "feat(report): add out-of-report llm mode for dialogue flow"
```

## Task 4: Run Full Focused Verification

**Files:**
- Modify: `app/services/report_qa_service.py`
- Modify: `tests/test_report_qa_service.py`
- Test: `tests/test_report_qa_service.py`
- Test: `tests/test_financial_report_usecase.py`
- Test: `tests/test_financial_report_api.py`

- [ ] **Step 1: Run the focused report-QA suite**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' tests/test_report_qa_service.py
```

Expected:

- all report-QA tests pass

- [ ] **Step 2: Run related regression coverage**

Run:

```bash
.venv/bin/python -m pytest -p no:cov -q --override-ini addopts='' \
  tests/test_report_qa_service.py \
  tests/test_financial_report_usecase.py \
  tests/test_financial_report_api.py
```

Expected:

- all related tests pass

- [ ] **Step 3: Commit the final green state if Task 4 required fixes**

If Task 4 exposed failures and you had to make additional edits, commit them separately.

```bash
git add app/services/report_qa_service.py tests/test_report_qa_service.py
git commit -m "test(report): stabilize dialogue regression coverage"
```

## Self-Review

- Spec coverage:
  - rule-only dialogue: Task 1
  - hybrid dialogue: Task 2
  - follow-up anchoring dialogue: Task 2
  - scope boundary dialogue with `out_of_report_llm`: Task 3
  - focused verification: Task 4
- Placeholder scan:
  - no `TODO`, `TBD`, or unnamed helper references remain
- Type consistency:
  - helper returns `tuple[payload, session_summary]`
  - production out-of-scope branch uses `answer_general_question_with_llm(...)`
  - `updated_session_summary` preservation always uses the incoming `session_summary` in the out-of-scope branch
