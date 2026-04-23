from __future__ import annotations

import subprocess

import pytest

from app.services import financial_report_service as report_service
from app.services.financial_report_service import (
    build_autoread_llm_excerpt,
    extract_financial_row_from_report_text,
    extract_report_assessment_metrics,
    fetch_report_text_from_url,
    select_latest_annual_report,
)


def test_extract_financial_row_from_chinese_report_text() -> None:
    text = """
    2024年年度报告摘要。公司2024年实现营业收入1,234.56亿元，
    归属于上市公司股东的净利润98.76亿元，净资产收益率15.2%，资产负债率48.6%。
    报告期：2024年12月31日。
    """
    payload = extract_financial_row_from_report_text(text)

    assert payload["report_year"] == 2024
    assert payload["report_date"] == "2024-12-31"
    assert payload["revenue"] == 1234.56 * 100000000
    assert payload["net_profit"] == 98.76 * 100000000
    assert payload["roe"] == 15.2
    assert payload["debt_ratio"] == 48.6
    assert len(payload["evidence"]) >= 4
    for evidence in payload["evidence"]:
        assert "parsed_value" in evidence
        assert "distance" in evidence
        assert "score" in evidence


def test_extract_financial_row_handles_pdf_whitespace_split_metric_keyword() -> None:
    text = """
    宁德时代新能源科技股份有限公司2025年年度报告全文
    主要会计数据和财务指标
    单位：千元
    营业收入 423,701,834 362,012,554 17.04%
    归属于上市公司股东的净利润 72,201,282 50,744,682 42.28%
    加权平均净资产收益
    率 24.91% 24.13% 0.78% 24.04%
    资产负债率 61.94% 65.24% -3.30%
    """

    payload = extract_financial_row_from_report_text(text, title="1225002214.PDF")

    assert payload["roe"] == 24.91


def test_extract_financial_row_infers_percent_unit_from_metric_header() -> None:
    text = """
    贵州茅台2025年年度报告
    主要会计数据和财务指标
    项目 2025年 2024年 本年比上年增减 2023年
    加权平均净资产收益率（%） 32.53 36.02 减少3.49个百分点 34.19
    资产负债率（%） 37.89 40.72 -2.83 41.15
    """

    payload = extract_financial_row_from_report_text(text, title="贵州茅台2025年年度报告")

    assert payload["roe"] == 32.53
    assert payload["debt_ratio"] == 37.89


def test_extract_financial_row_ignores_debt_ratio_threshold_in_guarantee_section() -> None:
    text = """
    内蒙古伊利实业集团股份有限公司2024年年度报告
    流动比率 0.74 0.90 -17.78
    速动比率 0.62 0.74 -16.22
    资产负债率（%） 62.91 62.19 1.16
    EBITDA全部债务比 0.27 0.31 -12.90

    公司担保总额情况（包括对子公司的担保）
    直接或间接为资产负债率超过70%的被担保对象提供的债务担保金额（D） 9,749.34
    """

    payload = extract_financial_row_from_report_text(text, title="内蒙古伊利实业集团股份有限公司2024年年度报告")

    assert payload["debt_ratio"] == 62.91


def test_extract_financial_row_extracts_balance_sheet_skeleton_fields() -> None:
    text = """
    宜宾五粮液股份有限公司2024年年度报告
    主要会计数据和财务指标
    2024 年末 2023 年末 本年末比上年末增减 2022 年末
    总资产（元） 188,252,218,704.17 165,432,981,684.75 13.79% 152,811,927,251.18
    归属于上市公司股东的净资产（元） 133,285,282,015.97 129,558,241,040.51 2.88% 114,027,897,212.18

    合并资产负债表
    单位：元
    流动负债合计 51,026,506,357.06 32,683,139,984.65
    非流动负债合计 830,918,614.42 400,468,512.93
    负债合计 51,857,424,971.48 33,083,608,497.58
    所有者权益合计 136,394,793,732.69 132,349,373,187.17
    """

    payload = extract_financial_row_from_report_text(text, title="宜宾五粮液股份有限公司2024年年度报告")

    assert payload["total_assets"] == 188252218704.17
    assert payload["attributable_equity"] == 133285282015.97
    assert payload["total_liabilities"] == 51857424971.48
    assert payload["net_assets"] == 136394793732.69


def test_extract_financial_row_extracts_priority_balance_sheet_detail_fields() -> None:
    text = """
    某公司2024年年度报告
    资产构成重大变动情况
    单位：元
    货币资金 127,398,915,484.11 67.67% 115,456,300,910.64 69.79% -2.12%
    应收账款 37,346,561.95 0.02% 42,647,461.48 0.03% -0.01%
    存货 18,233,702,166.62 9.69% 17,387,841,712.87 10.51% -0.82%
    固定资产 7,264,740,683.62 3.86% 5,189,917,302.17 3.14% 0.72%
    在建工程 5,795,172,321.07 3.08% 5,623,356,422.20 3.40% -0.32%

    合并资产负债表
    单位：元
    商誉 1,621,619.53 1,621,619.53
    """

    payload = extract_financial_row_from_report_text(text, title="某公司2024年年度报告")

    assert payload["monetary_funds"] == 127398915484.11
    assert payload["accounts_receivable"] == 37346561.95
    assert payload["inventory"] == 18233702166.62
    assert payload["fixed_assets"] == 7264740683.62
    assert payload["construction_in_progress"] == 5795172321.07
    assert payload["goodwill"] == 1621619.53


def test_extract_financial_row_derives_interest_bearing_debt_without_matching_goodwill_narrative() -> None:
    text = """
    海尔智家股份有限公司2025年年度报告
    关键审计事项
    截至2025年12月31日，商誉的账面价值为273.00亿元。

    合并资产负债表
    单位：元
    短期借款 17,420,784,420.86 13,784,367,443.93
    一年内到期的非流动负债 8,678,897,462.98 16,530,040,461.37
    长期借款 11,165,886,169.09 9,665,074,313.67
    应付债券 3,500,000,000.00 -
    租赁负债 4,551,410,567.84 4,480,895,997.36
    商誉
    """

    payload = extract_financial_row_from_report_text(text, title="海尔智家股份有限公司2025年年度报告")

    assert payload["goodwill"] is None
    assert payload["interest_bearing_debt"] == pytest.approx(
        17420784420.86
        + 8678897462.98
        + 11165886169.09
        + 3500000000.00
        + 4551410567.84
    )


def test_extract_financial_row_does_not_take_next_field_value_for_empty_goodwill_row() -> None:
    text = """
    贵州茅台2025年年度报告
    合并资产负债表
    单位：元
    开发支出 117,009,982.85 98,522,878.42
    商誉
    长期待摊费用 135,324,580.08 152,105,949.85
    """

    payload = extract_financial_row_from_report_text(text, title="贵州茅台2025年年度报告")

    assert payload["goodwill"] is None


def test_extract_financial_row_ignores_inventory_risk_paragraph_numbering() -> None:
    text = """
    海尔智家股份有限公司2025年年度报告
    9、存货风险。由于公司不能总是准确地预测各种趋势和事件，并始终保持足够的存货水平。
    10、资本开支风险：全球经济增速放缓以及消费需求预期下滑的宏观环境背景下，市场需求可能无法及时吸纳现有产能。

    资产构成重大变动情况
    单位：元
    存货 52,345,678,901.23 48,765,432,109.87
    """

    payload = extract_financial_row_from_report_text(text, title="海尔智家股份有限公司2025年年度报告")

    assert payload["inventory"] == 52345678901.23


def test_extract_financial_row_ignores_inventory_impairment_narrative_numbering() -> None:
    text = """
    海尔智家股份有限公司2025年年度报告
    公司会管理存货并根据市场情况作出调整，同时也会定期评估存货减值。
    10、资本开支风险：全球经济增速放缓以及消费需求预期下滑的宏观环境背景下，市场需求可能无法及时吸纳现有产能。
    """

    payload = extract_financial_row_from_report_text(text, title="海尔智家股份有限公司2025年年度报告")

    assert payload["inventory"] is None


def test_extract_financial_row_with_sparse_text() -> None:
    text = "这是一个公告页面，但没有关键财务指标。"
    payload = extract_financial_row_from_report_text(text, title="测试公告")

    assert payload["report_year"] is None
    assert payload["revenue"] is None
    assert payload["net_profit"] is None
    assert payload["roe"] is None
    assert payload["debt_ratio"] is None
    assert any("Revenue" in warning for warning in payload["warnings"])


def test_extract_report_assessment_metrics_extracts_quality_fields() -> None:
    text = """
    2024年年度报告。公司2024年实现营业收入1,000亿元，
    归属于上市公司股东的净利润120亿元，
    归属于上市公司股东的扣除非经常性损益的净利润110亿元，
    经营活动产生的现金流量净额130亿元，
    购建固定资产、无形资产和其他长期资产支付的现金40亿元，
    净资产收益率16.5%，资产负债率45.1%。
    报告期：2024年12月31日。
    """
    payload = extract_report_assessment_metrics(text)

    assert payload["report_year"] == 2024
    assert payload["report_date"] == "2024-12-31"
    assert payload["deducted_net_profit"] == 110 * 100000000
    assert payload["operating_cash_flow"] == 130 * 100000000
    assert payload["capex_cash_outflow"] == 40 * 100000000
    assert len(payload["evidence"]) >= 7


def test_extract_report_assessment_metrics_preserves_balance_sheet_skeleton_fields() -> None:
    text = """
    贵州茅台2025年年度报告
    主要会计数据和财务指标
    2025年末 2024年末 本期末比上年同期末增减（%） 2023年末
    归属于上市公司股东的净资产 244,637,811,032.18 233,105,984,399.47 4.95 215,668,571,607.43
    总资产 303,834,844,021.44 298,944,579,918.70 1.64 272,699,660,092.25
    经营活动产生的现金流量净额 92,463,692,168.43 66,508,744,851.05 39.03%
    合并资产负债表
    单位：元
    负债合计 49,875,590,112.37 56,933,264,798.10
    所有者权益（或股东权益）合计 253,959,253,909.07 242,011,315,120.60
    """

    payload = extract_report_assessment_metrics(text, title="贵州茅台2025年年度报告")

    assert payload["total_assets"] == 303834844021.44
    assert payload["attributable_equity"] == 244637811032.18
    assert payload["total_liabilities"] == 49875590112.37
    assert payload["net_assets"] == 253959253909.07


def test_extract_report_assessment_metrics_prefers_title_year_over_future_mentions() -> None:
    text = """
    2026年3月发布。公司计划在2028年继续扩大海外业务。
    报告期内公司实现营业收入4,585亿元，归母净利润439.5亿元，
    加权平均净资产收益率19.70%，资产负债率60.54%。
    """
    payload = extract_report_assessment_metrics(text, title="2025年年度报告")

    assert payload["report_year"] == 2025
    assert payload["report_date"] == "2025-12-31"


def test_extract_financial_row_prefers_annual_report_title_in_body_over_signature_and_future_years() -> None:
    text = """
    宁德时代新能源科技股份有限公司2025年年度报告全文
    董事长：曾毓群
    宁德时代新能源科技股份有限公司
    2026年3月9日

    国际能源署（IEA）预测，到2050年实现净零排放，全球年度能源投资将持续增长。

    主要会计数据和财务指标
    单位：百万元
    项目 2025年 2024年 本年比上年增减
    营业收入 423,701 362,013 17.04%
    归属于上市公司股东的净利润 72,201 50,745 42.28%
    资产负债率 61.94% 65.24% -3.30%
    """

    payload = extract_financial_row_from_report_text(text, title="1225002214.PDF")

    assert payload["report_year"] == 2025
    assert payload["report_date"] == "2025-12-31"


def test_extract_financial_row_uses_unit_context_and_ignores_merger_zero_profit_note() -> None:
    text = """
    宁德时代新能源科技股份有限公司2025年年度报告全文

    主要会计数据和财务指标
    单位：百万元
    项目 2025年 2024年 本年比上年增减
    营业收入 423,701 362,013 17.04%
    归属于上市公司股东的净利润 72,201 50,745 42.28%
    资产负债率 61.94% 65.24% -3.30%

    控制下企业合并的，被合并方在合并前实现的净利润为：0元，上期被合并方实现的净利润为：0元。
    """

    payload = extract_financial_row_from_report_text(text, title="1225002214.PDF")

    assert payload["revenue"] == 423701 * 1000000
    assert payload["net_profit"] == 72201 * 1000000
    assert payload["debt_ratio"] == 61.94
    net_profit_evidence = next(item for item in payload["evidence"] if item["metric"] == "net_profit")
    assert "被合并方" not in net_profit_evidence["snippet"]


def test_extract_financial_row_ignores_section_index_before_revenue_keyword() -> None:
    text = """
    宁德时代新能源科技股份有限公司2025年年度报告全文
    五、主要会计数据和财务指标
    1）营业收入整体情况
    单位：千元
    项目 2025年 2024年 本年比上年增减 2023年
    营业收入 423,701,834 362,012,554 17.04% 400,917,045
    归属于上市公司股东的净利润 72,201,282 50,744,682 42.28% 44,121,248
    """

    payload = extract_financial_row_from_report_text(text, title="1225002214.PDF")

    assert payload["revenue"] == 423701834 * 1000
    revenue_evidence = next(item for item in payload["evidence"] if item["metric"] == "revenue")
    assert revenue_evidence["raw_number"] == "423,701,834"


def test_extract_report_assessment_metrics_rejects_unitless_cash_flow_amount() -> None:
    text = """
    2025年年度报告。营业收入4,585亿元，归母净利润439.5亿元，
    资产负债率60.54%，加权平均净资产收益率19.70%。
    经营活动产生的现金流量净额 14,320,968 22,960,047 19,785,070 -3,720,155。
    """
    payload = extract_report_assessment_metrics(text, title="2025年年度报告")

    assert payload["operating_cash_flow"] is None
    assert "Operating cash flow was not reliably extracted." in payload["warnings"]


def test_extract_report_assessment_metrics_reads_primary_metrics_table_amounts() -> None:
    text = """
    贵州茅台2024年年度报告
    主要会计数据和财务指标
    单位：元
    项目 2024年 2023年 本年比上年增减
    营业收入 170,899,152,276.34 147,693,604,994.14 15.71%
    归属于上市公司股东的净利润 86,228,146,421.62 74,734,071,550.75 15.38%
    归属于上市公司股东的扣除非经常性损益的净利润 86,240,905,977.42 74,752,564,425.52 15.37%
    经营活动产生的现金流量净额 92,463,692,168.43 66,508,744,851.05 39.03%
    购建固定资产、无形资产和其他长期资产支付的现金 4,676,040,399.80 3,520,447,187.31 32.82%
    """

    payload = extract_report_assessment_metrics(text, title="贵州茅台2024年年度报告")

    assert payload["report_year"] == 2024
    assert payload["report_date"] == "2024-12-31"
    assert payload["deducted_net_profit"] == 86240905977.42
    assert payload["operating_cash_flow"] == 92463692168.43
    assert payload["capex_cash_outflow"] == 4676040399.80


def test_extract_report_assessment_metrics_reads_cash_flow_statement_lines_with_carried_unit() -> None:
    text = """
    宜宾五粮液股份有限公司2024年年度报告
    合并现金流量表
    单位：元
    经营活动产生的现金流量净额 33,939,755,192.78 41,742,479,908.23 -18.69%
    投资活动现金流入小计 24,089,041.18 25,404,357.88 -5.18%
    购建固定资产、无形资产和其他长期资产支付的现金 2,666,310,780.23 2,957,236,682.34
    """

    payload = extract_report_assessment_metrics(text, title="宜宾五粮液股份有限公司2024年年度报告")

    assert payload["operating_cash_flow"] == 33939755192.78
    assert payload["capex_cash_outflow"] == 2666310780.23


def test_extract_report_assessment_metrics_reads_split_capex_line_across_adjacent_rows() -> None:
    text = """
    某公司2024年年度报告
    合并现金流量表
    单位：元
    投资活动现金流入小计 24,089,041.18 25,404,357.88
    购建固定资产、无形资产和其他长期资
    产支付的现金 2,666,310,780.23 2,957,236,682.34
    投资支付的现金 1,000,000.00 2,000,000.00
    """

    payload = extract_report_assessment_metrics(text, title="某公司2024年年度报告")

    assert payload["capex_cash_outflow"] == 2666310780.23


def test_extract_report_assessment_metrics_prefers_annual_deducted_profit_and_applies_thousand_unit() -> None:
    text = """
    美的集团股份有限公司2025年年度报告
    六、主要会计数据和财务指标
    公司是否需追溯调整或重述以前年度会计数据
    □ 是 √ 否
     2025 年 2024 年 本年比上年增减 2023 年
    营业收入（千元） 456,451,731 407,149,600 12.11% 372,037,280
    归属于上市公司股东的净利润（千元） 43,945,411 38,537,237 14.03% 33,719,935
    归属于上市公司股东的扣除非经常性损
    益的净利润（千元） 41,267,233 35,741,418 15.46% 32,974,908
    经营活动产生的现金流量净额（千元） 53,345,930 60,511,572 -11.84% 57,902,611
    加权平均净资产收益率 19.70% 21.29% -1.59% 22.23%
    2025 年末 2024 年末 本年末比上年末增减 2023 年末
    总资产（千元） 608,791,766 604,351,853 0.73% 486,038,184
    归属于上市公司股东的净资产（千元） 223,221,305 216,750,057 2.99% 162,878,825

    分季度主要财务指标
    第一季度 第二季度 第三季度 第四季度
    归属于上市公司股东的扣除非经常性损益的净利润 12,749,867 13,485,532 10,904,681 4,127,153
    经营活动产生的现金流量净额 14,320,968 22,960,047 19,785,070 -3,720,155
    """

    payload = extract_report_assessment_metrics(text, title="美的集团股份有限公司2025年年度报告")

    assert payload["revenue"] == 456_451_731_000.0
    assert payload["net_profit"] == 43_945_411_000.0
    assert payload["deducted_net_profit"] == 41_267_233_000.0
    assert payload["operating_cash_flow"] == 53_345_930_000.0
    deducted_evidence = next(item for item in payload["evidence"] if item["metric"] == "deducted_net_profit")
    assert "41,267,233" in deducted_evidence["raw_number"]
    assert "12,749,867" not in deducted_evidence["snippet"]


def test_build_autoread_llm_excerpt_prefers_three_question_relevant_segments() -> None:
    text = """
    2025年年度报告
    公司坚持科技领先和全球突破，整体收入保持增长。

    目录
    第一节 重要提示
    第二节 公司简介

    管理层讨论与分析
    报告期内，公司海外电商和OBM业务继续增长，整体收入增长主要来自海外渠道拓展和产品结构升级。

    非经常性损益项目
    政府补助和公允价值变动收益对利润有影响，但扣除非经常性损益后的净利润仍保持增长。

    经营活动产生的现金流量净额
    经营活动产生的现金流量净额同比提升，现金回款质量改善。

    资本开支
    公司持续投入智能制造、海外工厂建设和自动化产线升级，在建工程和固定资产投入增加。

    风险提示
    海外关税、汇率和原材料价格波动可能影响未来利润率。
    """

    excerpt = build_autoread_llm_excerpt(text, title="2025年年度报告", max_chars=500)

    assert "整体收入增长主要来自海外渠道拓展和产品结构升级" in excerpt
    assert "扣除非经常性损益后的净利润仍保持增长" in excerpt
    assert "经营活动产生的现金流量净额同比提升" in excerpt
    assert "智能制造、海外工厂建设和自动化产线升级" in excerpt
    assert "目录" not in excerpt
    assert len(excerpt) <= 500


def test_select_latest_annual_report_prefers_full_report() -> None:
    candidates = [
        {
            "title": "2024年年度报告摘要",
            "published_at": "2025-03-20 18:00:00",
            "detail_url": "a",
            "document_url": "a.pdf",
        },
        {
            "title": "2024年年度报告",
            "published_at": "2025-03-20 18:01:00",
            "detail_url": "b",
            "document_url": "b.pdf",
        },
        {
            "title": "2023年年度报告",
            "published_at": "2024-03-18 09:00:00",
            "detail_url": "c",
            "document_url": "c.pdf",
        },
    ]

    selected = select_latest_annual_report(candidates)
    assert selected is not None
    assert selected["document_url"] == "b.pdf"


class _DummyResponse:
    def __init__(self, payload: bytes, content_type: str, final_url: str | None = None) -> None:
        self._payload = payload
        self.headers = {"Content-Type": content_type}
        self._final_url = final_url

    def read(self, _size: int = -1) -> bytes:
        return self._payload

    def geturl(self) -> str | None:
        return self._final_url

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_fetch_report_text_from_url_pdf_branch(monkeypatch) -> None:
    dummy_pdf_bytes = b"%PDF-1.4 FAKE"

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        assert timeout == 12
        assert context is not None
        return _DummyResponse(dummy_pdf_bytes, "application/pdf")

    def fake_extract_pdf_text(raw: bytes, max_pages: int = 120):  # noqa: ANN001
        assert raw == dummy_pdf_bytes
        assert max_pages == 120
        return ("2024年 营业收入 100 亿元 净利润 10 亿元 ROE 15% 资产负债率 45%", 88)

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.setattr(report_service, "_extract_pdf_text", fake_extract_pdf_text)

    out = fetch_report_text_from_url("https://static.cninfo.com.cn/reports/annual-2024.pdf")
    assert out["content_type"] == "application/pdf"
    assert out["title"] == "annual-2024.pdf"
    assert out["pdf_pages"] == 88
    assert out["tls_insecure"] is False
    assert "营业收入" in out["text"]


def test_extract_pdf_text_without_available_parser(monkeypatch) -> None:
    monkeypatch.setattr(report_service, "PdfReader", None)
    monkeypatch.setattr(report_service.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError) as exc_info:
        report_service._extract_pdf_text(b"%PDF-1.4 fake")
    assert "Failed to parse PDF text" in str(exc_info.value)


def test_extract_pdf_text_rejects_raw_pdf_structure_dump(monkeypatch) -> None:
    monkeypatch.setattr(report_service, "PdfReader", None)
    monkeypatch.setattr(report_service.shutil, "which", lambda _name: "/usr/bin/textutil")

    def fake_run(*_args, **_kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=["textutil"],
            returncode=0,
            stdout=(
                "%PDF-1.7\n"
                "1 0 obj\n"
                "<</Type/Catalog/Pages 2 0 R>>\n"
                "stream\n"
                "BT /F1 12 Tf ET\n"
                "endstream\n"
                "endobj\n"
                "xref\n"
                "trailer\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(report_service.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        report_service._extract_pdf_text(b"%PDF-1.4 fake")
    assert "Failed to parse PDF text" in str(exc_info.value)
    assert "unreadable" in str(exc_info.value).lower()


def test_fetch_report_text_from_url_ssl_verify_failure_with_hint(monkeypatch) -> None:
    class _SslVerifyError(Exception):
        pass

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        _ = timeout, context
        raise RuntimeError("certificate verify failed")

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.delenv("REPORT_URL_INSECURE_SSL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        fetch_report_text_from_url("https://static.cninfo.com.cn/report.pdf")
    assert "TLS certificate verification failed" in str(exc_info.value)


def test_fetch_report_text_from_url_pdf_size_limit(monkeypatch) -> None:
    payload = b"%PDF-1.4 " + (b"A" * 1_000_100)

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        _ = timeout, context
        return _DummyResponse(payload, "application/pdf")

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)
    monkeypatch.setenv("REPORT_PDF_MAX_MB", "1")

    with pytest.raises(RuntimeError) as exc_info:
        fetch_report_text_from_url("https://static.cninfo.com.cn/big.pdf")
    assert "PDF file is too large to parse" in str(exc_info.value)


def test_fetch_report_text_from_url_rejects_non_whitelisted_host() -> None:
    with pytest.raises(ValueError) as exc_info:
        fetch_report_text_from_url("https://example.com/report.pdf")
    assert "official disclosure sources" in str(exc_info.value)


def test_fetch_report_text_from_url_rejects_redirect_to_non_whitelisted_host(monkeypatch) -> None:
    dummy_pdf_bytes = b"%PDF-1.4 FAKE"

    def fake_urlopen(_req, timeout: int = 0, context=None):  # noqa: ANN001
        assert timeout == 12
        assert context is not None
        return _DummyResponse(
            dummy_pdf_bytes,
            "application/pdf",
            final_url="https://example.com/report.pdf",
        )

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError) as exc_info:
        fetch_report_text_from_url("https://static.cninfo.com.cn/report.pdf")
    assert "redirected to a non-whitelisted host" in str(exc_info.value)


def test_post_cninfo_disclosure_query_uses_https_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout: int = 0, context=None):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["origin"] = req.headers.get("Origin")
        captured["referer"] = req.headers.get("Referer")
        captured["context"] = context
        assert timeout == 12
        return _DummyResponse(b'{"announcements": []}', "application/json; charset=utf-8")

    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)

    payload = report_service._post_cninfo_disclosure_query({"pageNum": "1"})

    assert payload == {"announcements": []}
    assert captured["url"] == "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    assert captured["origin"] == "https://www.cninfo.com.cn"
    assert str(captured["referer"]).startswith("https://www.cninfo.com.cn/")
    assert captured["context"] is not None


def test_load_cninfo_symbol_org_map_uses_verified_ssl_context(monkeypatch) -> None:
    sentinel_context = object()
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout: int = 0, context=None):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["context"] = context
        assert timeout == 12
        return _DummyResponse(b'{"stockList":[{"code":"600519","orgId":"gssh0600519"}]}', "application/json; charset=utf-8")

    monkeypatch.setattr(report_service, "_build_verified_ssl_context", lambda: sentinel_context)
    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)

    payload = report_service._load_cninfo_symbol_org_map()

    assert payload == {"600519": "gssh0600519"}
    assert captured["url"] == "https://www.cninfo.com.cn/new/data/szse_stock.json"
    assert captured["context"] is sentinel_context


def test_post_cninfo_disclosure_query_uses_verified_ssl_context(monkeypatch) -> None:
    sentinel_context = object()
    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout: int = 0, context=None):  # noqa: ANN001
        captured["url"] = req.full_url
        captured["context"] = context
        assert timeout == 12
        return _DummyResponse(b'{"announcements": []}', "application/json; charset=utf-8")

    monkeypatch.setattr(report_service, "_build_verified_ssl_context", lambda: sentinel_context)
    monkeypatch.setattr(report_service, "urlopen", fake_urlopen)

    payload = report_service._post_cninfo_disclosure_query({"pageNum": "1"})

    assert payload == {"announcements": []}
    assert captured["url"] == "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    assert captured["context"] is sentinel_context
