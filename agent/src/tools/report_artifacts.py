"""Stage generated PDFs and DOCX documents for authenticated download and channel delivery."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any

from src.config.paths import get_runtime_root

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def reports_root() -> Path:
    """Return the runtime-only generated report directory."""
    return get_runtime_root() / "generated_reports"


def publish_report_artifact(path: Path, format: str | None = None) -> dict[str, Any]:
    """Stage an actual PDF or DOCX report and return its opaque download handle.

    Args:
        path: Successful report output, not a model-supplied download path.
        format: Optional format tag ('pdf' or 'docx'). Inferred from extension if None.

    Returns:
        Metadata for the staged file, including sha256 checksum and size.

    Raises:
        ValueError: The file is not a supported or valid document format.
    """
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"Report artifact file does not exist: {path}")

    fmt = (format or path.suffix.lstrip(".").lower()).lower()
    if fmt not in MEDIA_TYPES:
        raise ValueError(f"Unsupported report format '{fmt}'. Expected pdf, docx or pptx.")

    # Magic header check
    with path.open("rb") as stream:
        header = stream.read(8)
        if fmt == "pdf" and not header.startswith(b"%PDF-"):
            raise ValueError("The generated report is not a valid PDF")
        if fmt in ("docx", "pptx") and not header.startswith(b"PK\x03\x04"):
            raise ValueError(f"The generated report is not a valid {fmt.upper()} document")

    # Compute sha256 and size
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    sha256 = hasher.hexdigest()
    size_bytes = path.stat().st_size

    report_id = uuid.uuid4().hex
    directory = reports_root() / report_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / path.name
    shutil.copyfile(path, destination)

    return {
        "report_id": report_id,
        "download_url": f"/api/reports/{report_id}",
        "filename": path.name,
        "media_type": MEDIA_TYPES[fmt],
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def publish_pdf(path: Path) -> dict[str, str]:
    """Stage an actual PDF and return its opaque download handle (legacy wrapper)."""
    artifact = publish_report_artifact(path, format="pdf")
    return {
        "report_id": artifact["report_id"],
        "download_url": artifact["download_url"],
        "filename": artifact["filename"],
        "media_type": artifact["media_type"],
    }


def resolve_report_artifact(report_id: str, format: str | None = None) -> tuple[Path, str] | None:
    """Resolve an opaque report ID to its file path and MIME type.

    Refuses path traversal, non-hex IDs and symlink escapes.
    """
    if len(report_id) != 32 or any(char not in "0123456789abcdef" for char in report_id):
        return None
    directory = reports_root() / report_id
    if not directory.is_dir() or directory.is_symlink():
        return None

    files = [p for p in directory.iterdir() if p.is_file() and not p.is_symlink()]
    if format:
        target_ext = f".{format.lower().lstrip('.')}"
        files = [p for p in files if p.suffix.lower() == target_ext]

    if len(files) != 1:
        return None

    file_path = files[0]
    ext = file_path.suffix.lower().lstrip(".")
    media_type = MEDIA_TYPES.get(ext, "application/octet-stream")
    return file_path, media_type


def report_path(report_id: str) -> Path | None:
    """Resolve an opaque report ID, refusing traversal and symlink escapes (legacy wrapper)."""
    resolved = resolve_report_artifact(report_id)
    if resolved is not None:
        return resolved[0]
    return None
