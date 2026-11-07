"""Generate the evidence-based FPT deep research draft and check its PDF length."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from pypdf import PdfReader

from src.reporting.service import ReportJobService
from src.tools.report_artifacts import resolve_report_artifact


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=root / "src/reporting/templates/fpt_report_deep.json")
    parser.add_argument("--output-dir", type=Path, default=root.parent / "output/pdf")
    parser.add_argument("--min-pages", type=int, default=24)
    args = parser.parse_args(argv)
    if args.min_pages < 1:
        parser.error("--min-pages must be positive")
    data = json.loads(args.template.read_text(encoding="utf-8"))
    job = ReportJobService().create_job(data, formats=["docx", "pdf"])
    if job["status"] != "succeeded":
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 1

    resolved = []
    for artifact in job["artifacts"]:
        result = resolve_report_artifact(artifact["report_id"])
        if result is None:
            raise RuntimeError("Generated artifact could not be resolved")
        resolved.append(result[0])
    pdf_path = next(path for path in resolved if path.suffix == ".pdf")
    pages = len(PdfReader(pdf_path).pages)
    if pages < args.min_pages:
        raise RuntimeError(f"Report has {pages} pages, requires at least {args.min_pages}; expand the research content")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for path in resolved:
        destination = args.output_dir / path.name
        shutil.copyfile(path, destination)
        outputs.append(str(destination.resolve()))
    print(json.dumps({"job_id": job["job_id"], "publication_status": job["publication_status"],
                      "pdf_pages": pages, "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
