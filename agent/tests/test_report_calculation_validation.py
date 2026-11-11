"""The in-app export must check declared calculations before publishing them."""

import json

from docx import Document
import pytest

from src.agent.tool_context import current_grounding
from src.agent.grounding import GroundingLedger
from src.reporting.service import ReportJobService
from src.reporting.tool import ExportResearchReportTool
from tests.test_report_evidence_pipeline import _collected_page, research


def export_receipt(tmp_path, monkeypatch, payload, context):
    rendered = []

    def render(report, root, formats):
        rendered.append(report)
        path = root / "research.docx"
        Document().save(path)
        return {"docx": str(path)}

    monkeypatch.setattr("src.reporting.service.export_report", render)
    monkeypatch.setattr("src.reporting.tool.ReportJobService", lambda: ReportJobService(tmp_path / "jobs"))
    monkeypatch.setattr("src.reporting.evidence.from_grounding_ledger", lambda _: context)
    token = current_grounding.set(GroundingLedger(run_dir=tmp_path, user_message="Export the prepared report"))
    try:
        receipt = json.loads(ExportResearchReportTool().execute(payload, formats=["docx"]))
    finally:
        current_grounding.reset(token)
    return receipt, rendered


@pytest.mark.parametrize("inputs,key,value,unit,formula,expected", [
    ([('operating_cash_flow', 69245), ('capex', 74505)],
     'free_cash_flow', -96030, 'tỷ VND', 'operating_cash_flow - capex', -5260),
    ([('net_debt', 337297), ('total_assets', 1620000)],
     'debt_to_assets', 24.1, '%', 'net_debt / total_assets', 337297 / 1620000 * 100),
])
def test_unrated_export_rejects_wrong_declared_financial_calculation(
    tmp_path, monkeypatch, inputs, key, value, unit, formula, expected,
):
    report, context = research(tmp_path)
    context = _collected_page(tmp_path, context, "Kết quả hợp nhất: " + "; ".join(
        f"{name}: {amount} tỷ VND" for name, amount in inputs
    ))
    payload = report.model_dump(mode="json")
    payload['sources'].append({'id': 'IR1', 'title': 'Kết quả hợp nhất', 'provider': 'IR',
                               'url': 'https://ir.example.vn/kqkd-9t-2026'})
    payload['financial_metrics'].extend([
        {'key': name, 'label': name, 'value': amount, 'unit': 'tỷ VND',
         'as_of': '2026-09-30', 'source_ids': ['IR1']}
        for name, amount in inputs
    ] + [{'key': key, 'label': key, 'value': value, 'unit': unit, 'decimals': 1,
          'as_of': '2026-09-30', 'evidence_kind': 'derived',
          'input_keys': [name for name, _ in inputs], 'methodology': formula}])

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is False, "Unrated research still must satisfy its own declared arithmetic"
    assert receipt['error_code'] == 'EVIDENCE_VALIDATION_FAILED'
    assert not rendered
    issue = receipt['field_errors'][0]
    assert issue['field'] == 'financial_metrics.3.value'
    assert issue['expected_value'] == pytest.approx(expected)
    assert issue['formula'] == formula
    assert set(issue['inputs']) == {name for name, _ in inputs}
    assert receipt['accepted_report']['financial_metrics'][3]['value'] == value
    repaired = receipt['accepted_report']
    repaired['financial_metrics'][3]['value'] = issue['expected_value']
    retry, rendered = export_receipt(tmp_path, monkeypatch, repaired, context)
    assert retry['ok'] is True
    assert len(rendered) == 1


def test_export_names_the_collected_url_when_a_source_id_is_mismatched(tmp_path, monkeypatch):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    collected_url = payload['sources'][0]['url']
    payload['sources'][0]['url'] = 'https://example.vn/guessed-source'

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['error_code'] == 'EVIDENCE_VALIDATION_FAILED'
    assert not rendered
    issue = receipt['field_errors'][0]
    assert issue['field'] == 'sources.0.url'
    assert issue['expected_url'] == collected_url
    assert issue['source_id'] == payload['sources'][0]['id']
    assert receipt['accepted_report']['sources'][0]['url'] == payload['sources'][0]['url']
    repaired = receipt['accepted_report']
    repaired['sources'][0]['url'] = issue['expected_url']
    retry, rendered = export_receipt(tmp_path, monkeypatch, repaired, context)
    assert retry['ok'] is True
    assert len(rendered) == 1


@pytest.mark.parametrize('methodology', ['Chiết khấu dòng tiền kết hợp P/E mục tiêu', 'DCF/SOTP'])
def test_legacy_prose_methodology_remains_a_draft_with_a_calculation_warning(tmp_path, monkeypatch, methodology):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    payload['valuation_metrics'] = [{
        'key': 'target_price', 'label': 'Giá trị kịch bản', 'value': 55880, 'unit': 'VND',
        'as_of': '2026-11-06', 'price_basis': 'raw', 'evidence_kind': 'derived',
        'input_keys': ['market_price'], 'methodology': methodology,
    }]

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is True
    assert receipt['publication_status'] == 'draft_unverified'
    assert any('chưa kiểm chứng được phép tính' in warning for warning in receipt['warnings'])
    assert len(rendered) == 1


def test_export_batches_calculation_and_source_repairs_in_a_shrinking_field_set(tmp_path, monkeypatch):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    payload['sources'][0]['url'] = 'https://example.vn/guessed-source'
    payload['financial_metrics'].extend([
        {'key': f'calculation_{index}', 'label': 'Calculation', 'value': 1, 'unit': 'VND',
         'as_of': '2026-11-06', 'evidence_kind': 'derived', 'input_keys': ['market_price'],
         'methodology': 'market_price * 1'}
        for index in range(2)
    ])

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)
    assert not rendered
    assert {issue['field'] for issue in receipt['field_errors']} == {
        'financial_metrics.1.value', 'financial_metrics.2.value', 'sources.0.url',
    }
    repaired = receipt['accepted_report']
    repaired['financial_metrics'][1]['value'] = receipt['field_errors'][0]['expected_value']
    retry, rendered = export_receipt(tmp_path, monkeypatch, repaired, context)
    assert not rendered
    assert {issue['field'] for issue in retry['field_errors']} == {'financial_metrics.2.value', 'sources.0.url'}
    repaired['financial_metrics'][2]['value'] = retry['field_errors'][0]['expected_value']
    repaired['sources'][0]['url'] = retry['field_errors'][1]['expected_url']
    completed, rendered = export_receipt(tmp_path, monkeypatch, repaired, context)
    assert completed['ok'] is True
    assert len(rendered) == 1


def test_unrated_calculation_without_a_value_remains_explicitly_unavailable(tmp_path, monkeypatch):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    payload['financial_metrics'].append({
        'key': 'unavailable', 'label': 'Chưa có dữ liệu', 'value': None, 'unit': 'VND',
        'evidence_kind': 'derived', 'input_keys': ['market_price'], 'methodology': 'market_price * 1',
    })

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is True
    assert rendered[0].financial_metrics[1].value is None


def cashflow_payload(tmp_path):
    report, context = research(tmp_path)
    context = _collected_page(tmp_path, context, "CFO: 69245 tỷ VND; CAPEX: 74505 tỷ VND")
    payload = report.model_dump(mode='json')
    payload['sources'].append({'id': 'IR1', 'title': 'Cash flow statement', 'provider': 'IR',
                               'url': 'https://ir.example.vn/kqkd-9t-2026'})
    payload['financial_metrics'].extend([
        {'key': key, 'label': key, 'value': value, 'unit': 'tỷ VND',
         'as_of': '2026-09-30', 'source_ids': ['IR1']}
        for key, value in [('cfo', 69245), ('capex', 74505)]
    ] + [{'key': 'fcf', 'label': 'Cash flow proxy', 'value': -5260, 'unit': 'tỷ VND',
          'as_of': '2026-09-30', 'evidence_kind': 'derived',
          'input_keys': ['cfo', 'capex'], 'methodology': 'cfo - capex'}])
    return payload, context


def test_export_rejects_cash_flow_subtraction_from_different_periods(tmp_path, monkeypatch):
    payload, context = cashflow_payload(tmp_path)
    payload['financial_metrics'][2]['as_of'] = '2025-12-31'

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is False
    assert receipt['error_code'] == 'EVIDENCE_VALIDATION_FAILED'
    assert not rendered
    issue = receipt['field_errors'][0]
    assert issue['field'] == 'financial_metrics.3.value'
    assert {item['as_of'] for item in issue['inputs'].values()} == {'2026-09-30', '2025-12-31'}
    payload['financial_metrics'][2]['as_of'] = '2026-09-30'
    retry, rendered = export_receipt(tmp_path, monkeypatch, payload, context)
    assert retry['ok'] is True
    assert len(rendered) == 1


@pytest.mark.parametrize('methodology', ['cfo - capex; calculated from statements', 'cfo -'])
def test_export_rejects_malformed_arithmetic_instead_of_downgrading_it_to_prose(
    tmp_path, monkeypatch, methodology,
):
    payload, context = cashflow_payload(tmp_path)
    payload['financial_metrics'][3].update(value=-96030, methodology=methodology)

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is False
    assert receipt['error_code'] == 'EVIDENCE_VALIDATION_FAILED'
    assert receipt['field_errors'][0]['field'] == 'financial_metrics.3.value'
    assert not rendered


def test_valuation_can_combine_a_current_quote_with_an_earlier_eps_date(tmp_path, monkeypatch):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    payload['valuation_metrics'] = [
        {'key': 'eps', 'label': 'Forecast EPS', 'value': 2540, 'unit': 'VND',
         'as_of': '2026-09-30', 'evidence_kind': 'assumption', 'methodology': 'Explicit forecast'},
        {'key': 'pe', 'label': 'Scenario P/E', 'value': 22, 'unit': 'x',
         'as_of': '2026-11-06', 'evidence_kind': 'assumption', 'methodology': 'Explicit multiple'},
        {'key': 'target_price', 'label': 'Scenario price', 'value': 55880, 'unit': 'VND',
         'as_of': '2026-11-06', 'price_basis': 'raw', 'evidence_kind': 'derived',
         'input_keys': ['eps', 'pe'], 'methodology': 'eps * pe'},
    ]

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is True
    assert len(rendered) == 1


@pytest.mark.parametrize('share_unit,eps_unit', [('shares', 'VND/share'), ('SHARE', 'VND/SHARES'), ('CP', 'VND/CP')])
@pytest.mark.parametrize('eps_value', [1000, 999])
def test_export_checks_eps_with_explicit_share_unit_aliases(
    tmp_path, monkeypatch, share_unit, eps_unit, eps_value,
):
    report, context = research(tmp_path)
    context = _collected_page(tmp_path, context, 'Net profit: 1000000000 VND; Shares: 1000000')
    payload = report.model_dump(mode='json')
    payload['sources'].append({'id': 'IR1', 'title': 'Earnings and shares', 'provider': 'IR',
                               'url': 'https://ir.example.vn/kqkd-9t-2026'})
    payload['financial_metrics'].extend([
        {'key': 'net_income', 'label': 'Net profit', 'value': 1000000000, 'unit': 'VND',
         'as_of': '2026-09-30', 'source_ids': ['IR1']},
        {'key': 'share_count', 'label': 'Shares', 'value': 1000000, 'unit': share_unit,
         'as_of': '2026-09-30', 'source_ids': ['IR1']},
        {'key': 'eps', 'label': 'EPS', 'value': eps_value, 'unit': eps_unit,
         'as_of': '2026-09-30', 'evidence_kind': 'derived',
         'input_keys': ['net_income', 'share_count'], 'methodology': 'net_income / share_count'},
    ])

    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)

    assert receipt['ok'] is (eps_value == 1000)
    if eps_value == 999:
        assert not rendered
        assert receipt['field_errors'][0]['expected_value'] == 1000
    else:
        assert len(rendered) == 1


def test_render_success_keeps_depth_feedback_for_the_ai(tmp_path, monkeypatch):
    report, context = research(tmp_path)
    payload = report.model_dump(mode='json')
    assert payload['analysis_sections'] == []
    receipt, rendered = export_receipt(tmp_path, monkeypatch, payload, context)
    assert receipt['ok'] is True
    assert len(rendered) == 1
    assert any('không có analysis_sections' in warning for warning in receipt['warnings'])
