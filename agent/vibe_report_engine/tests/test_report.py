import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from pydantic import ValidationError
from schema import ResearchReport
from renderer import export_report

ROOT = Path(__file__).resolve().parents[1]

def load():
    return json.loads((ROOT/'examples/demo_report.json').read_text(encoding='utf-8'))

def test_sample_valid():
    payload = ResearchReport.model_validate(load())
    assert payload.demo and payload.symbol == 'ABCXY'

def test_no_unresolved_citations():
    sample = load()
    sample['investment_theses'][0]['source_ids'] = ['BROKEN']
    with pytest.raises(ValidationError,match='Thiếu nguồn'):
        ResearchReport.model_validate(sample)

def test_prod_rejects_demo_sources():
    sample = load(); sample['demo'] = False
    with pytest.raises(ValidationError, match='xác minh'):
        ResearchReport.model_validate(sample)

def test_generate(tmp_path):
    report = ResearchReport.model_validate(load())
    result = export_report(report,tmp_path)
    assert Path(result['docx']).stat().st_size > 20000
    assert Path(result['pdf']).stat().st_size > 20000
