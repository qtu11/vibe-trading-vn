"""Export supplied research for any ticker and verify the requested PDF depth.

The filename is retained for existing scripts. Static inputs are unrated drafts;
live evidence-bound research is exported through the agent tool instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from pypdf import PdfReader

from src.reporting.service import ReportJobService
from src.tools.report_artifacts import resolve_report_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True, help="ResearchReport JSON for the requested ticker")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "output/pdf")
    parser.add_argument("--min-pages", type=int, default=24)
    args = parser.parse_args(argv)
    if args.min_pages < 1:
        parser.error("--min-pages must be positive")
    data = json.loads(args.template.read_text(encoding="utf-8"))
    job = ReportJobService().create_job(data, formats=["docx", "pdf", "pptx"], minimum_pages=args.min_pages)
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
        try:
            shutil.copyfile(path, destination)
            outputs.append(str(destination.resolve()))
        except PermissionError:
            alt = destination.with_stem(f"{destination.stem}_draft_{job['job_id'][:8]}")
            shutil.copyfile(path, alt)
            outputs.append(str(alt.resolve()))
    print(json.dumps({"job_id": job["job_id"], "publication_status": job["publication_status"],
                      "pdf_pages": pages, "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
