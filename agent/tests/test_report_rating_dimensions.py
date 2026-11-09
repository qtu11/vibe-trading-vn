"""Rated prices must preserve declared currency and ratio dimensions."""

import pytest

from src.reporting.evidence import _validate_rating_target, validate_report_evidence
from src.reporting.schema import Metric, ResearchReport
from tests.test_report_evidence_pipeline import research


def _rated_formula(report, inputs, formula, target=60000):
    payload = report.model_dump(mode='json')
    payload['recommendation'] = 'MUA'
    payload['valuation_metrics'] = [
        {'key': key, 'label': key, 'value': value, 'unit': unit, 'as_of': '2026-11-06',
         'evidence_kind': 'assumption', 'methodology': 'Explicit test assumption'}
        for key, value, unit in inputs
    ] + [{'key': 'target_price', 'label': 'Giá mục tiêu', 'value': target, 'unit': 'VND',
          'as_of': '2026-11-06', 'price_basis': 'raw', 'decimals': 2,
          'evidence_kind': 'derived', 'input_keys': [key for key, _, _ in inputs],
          'methodology': formula}]
    return payload


@pytest.mark.parametrize('inputs,formula,target', [
    ([('eps', 2000, 'USD/share'), ('pe', 30, 'x')], 'eps * pe', 60000),
    ([('eps', 2000, 'VND/cp'), ('pe', 30, 'USD')], 'eps * pe', 60000),
    ([('eps', 50000, 'VND'), ('adjustment', 10000, 'USD')], 'eps + adjustment', 60000),
    ([('eps', 60000, 'VND'), ('premium', 20, '%')], 'eps + premium', 60000.2),
    ([('eps', 2000, 'VND'), ('pe', 30, '')], 'eps * pe', 60000),
    ([('eps', 2, 'USD'), ('fx', 25000, 'USD/VND'), ('pe', 1.2, 'x')], 'eps * fx * pe', 60000),
])
def test_rated_arithmetic_rejects_incompatible_or_missing_units(tmp_path, inputs, formula, target):
    report, context = research(tmp_path)
    payload = _rated_formula(report, inputs, formula, target)
    with pytest.raises(ValueError, match='đơn vị|Đơn vị'):
        validate_report_evidence(ResearchReport.model_validate(payload), context)


def test_rated_arithmetic_accepts_explicit_currency_conversion(tmp_path):
    report, context = research(tmp_path)
    payload = _rated_formula(report,
        [('eps', 2, 'USD/share'), ('fx', 25000, 'VND/USD'), ('pe', 1.2, 'x')],
        'eps * fx * pe')
    assert validate_report_evidence(ResearchReport.model_validate(payload), context).quote_verified


def test_rated_arithmetic_normalizes_percentage_and_display_scale(tmp_path):
    report, context = research(tmp_path)
    payload = _rated_formula(report, [('price', 50.8, 'nghìn VND'), ('premium', 10, '%')],
                             'price * (1 + premium)', target=55880)
    assert validate_report_evidence(ResearchReport.model_validate(payload), context).quote_verified


def test_intermediate_metric_cannot_relabel_usd_as_vnd(tmp_path):
    report, context = research(tmp_path)
    payload = _rated_formula(report, [('eps', 2000, 'USD'), ('pe', 30, 'x')], 'converted * 1')
    payload['valuation_metrics'][-1]['input_keys'] = ['converted']
    payload['valuation_metrics'].insert(-1, {
        'key': 'converted', 'label': 'Converted EPS target', 'value': 60000, 'unit': 'VND',
        'as_of': '2026-11-06', 'evidence_kind': 'derived', 'input_keys': ['eps', 'pe'],
        'methodology': 'eps * pe',
    })
    with pytest.raises(ValueError, match='Đơn vị kết quả'):
        validate_report_evidence(ResearchReport.model_validate(payload), context)


@pytest.mark.parametrize('unit', ['VND', 'USD', 'USDT', 'USDC'])
def test_currency_dimension_preserves_declared_non_iso_quote_tokens(unit):
    metrics = {
        'price': Metric(key='price', label='Price', value=50, unit=unit, evidence_kind='observed'),
        'multiple': Metric(key='multiple', label='Multiple', value=1.2, unit='x', evidence_kind='assumption'),
        'target': Metric(key='target', label='Target', value=60, unit=unit, evidence_kind='derived',
                         input_keys=['price', 'multiple'], methodology='price * multiple'),
    }
    _validate_rating_target(metrics['target'], metrics)
