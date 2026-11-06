from pathlib import Path
import json
from schema import ResearchReport
from renderer import export_report

path = Path(__file__).parent
sample = ResearchReport.model_validate_json((path / "examples" / "demo_report.json").read_text(encoding="utf-8"))
result = export_report(sample, path / "outputs")
print(json.dumps(result, ensure_ascii=False, indent=2))
