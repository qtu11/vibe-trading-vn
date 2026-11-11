"""Immutable source snapshots and process-owned evidence delivery receipts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import threading
from typing import Any
import uuid

from src.agent.tool_context import current_grounding
from src.config.paths import get_runs_dir
from src.tools.path_utils import safe_run_dir
from src.security.scanner import neutralize_special_tokens, with_security_warnings

_LOCK = threading.RLock()
_DOCUMENTS: dict[str, dict[str, Any]] = {}


def _owner(run_dir: str | Path | None = None) -> Path:
    ledger = current_grounding.get()
    return Path(getattr(ledger, "run_dir", None) or run_dir or get_runs_dir() / "source-reader").resolve()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("Source snapshot integrity check failed") from None


def persist_document(*, source: str, content_type: str, content_bytes: bytes,
                     full_text: str = "", coverage: dict[str, Any] | None = None,
                     run_dir: str | Path | None = None, requested_url: str = "") -> dict[str, Any]:
    """Save all fetched bytes and extracted text before any delivery pruning."""
    owner = _owner(run_dir)
    full_text = neutralize_special_tokens(full_text.replace("\r\n", "\n").replace("\r", "\n"))
    root = safe_run_dir(str(run_dir or owner)) / "artifacts" / "sources"
    raw_sha = hashlib.sha256(content_bytes).hexdigest()
    text_bytes = full_text.encode("utf-8")
    text_sha = hashlib.sha256(text_bytes).hexdigest()
    suffix = ".pdf" if content_bytes.lstrip().startswith(b"%PDF-") else ".raw"
    artifact = root / f"{raw_sha}{suffix}"
    text_path = root / f"{raw_sha}-{text_sha}.txt"
    _write(artifact, content_bytes)
    _write(text_path, text_bytes)
    cov = dict(coverage or {})
    extraction_complete = cov.get("extraction_complete", cov.get("complete", bool(full_text.strip()))) is True
    cov.update(extraction_complete=extraction_complete, total_chars=len(full_text),
               text_delivery_complete=False, complete=False, returned_range={"start": 0, "end": 0})
    cov["status"] = "partial" if full_text else "blocked"
    descriptor = {"source": source, "url": source, "content_type": content_type,
                  "artifact_path": str(artifact), "text_path": str(text_path),
                  "full_text_path": str(text_path), "raw_sha256": raw_sha,
                  "text_sha256": text_sha, "coverage": cov}
    if requested_url:
        descriptor["requested_url"] = requested_url
    with _LOCK:
        for key, entry in list(_DOCUMENTS.items()):
            prior = entry["document"]
            if (entry["owner"] == str(owner) and prior["source"] == source
                    and prior.get("requested_url", "") == requested_url
                    and prior["raw_sha256"] == raw_sha and prior["text_sha256"] == text_sha
                    and prior["coverage"]["extraction_complete"] == extraction_complete):
                descriptor["coverage_id"] = key
                if requested_url:
                    prior["requested_url"] = requested_url
                prior["coverage"].update({name: value for name, value in cov.items()
                                          if name not in {"returned_range", "text_delivery_complete", "complete", "status"}})
                descriptor["coverage"] = deepcopy(prior["coverage"])
                _DOCUMENTS.pop(key)
                _DOCUMENTS[key] = entry
                return descriptor
        descriptor["coverage_id"] = uuid.uuid4().hex
        _DOCUMENTS[descriptor["coverage_id"]] = {"owner": str(owner), "document": deepcopy(descriptor), "ranges": []}
        while len(_DOCUMENTS) > 4096:
            _DOCUMENTS.pop(next(iter(_DOCUMENTS)))
    return descriptor


def _entry(document: dict[str, Any]) -> dict[str, Any] | None:
    entry = _DOCUMENTS.get(str(document.get("coverage_id", "")))
    if entry is None:
        return None
    original = entry["document"]
    ledger = current_grounding.get()
    if ledger is not None and str(_owner()) != entry["owner"]:
        return None
    if any(document.get(key) != original[key] for key in ("raw_sha256", "text_sha256")):
        return None
    try:
        for path_key, hash_key in (("artifact_path", "raw_sha256"), ("full_text_path", "text_sha256")):
            if hashlib.sha256(Path(document[path_key]).read_bytes()).hexdigest() != original[hash_key]:
                return None
    except (OSError, KeyError, TypeError):
        return None
    return entry


def current_document_coverage(document: dict[str, Any]) -> dict[str, Any]:
    """Ignore editable/model-supplied coverage flags; verify the saved bytes."""
    with _LOCK:
        entry = _entry(document)
        if entry is None:
            return {"status": "blocked", "complete": False, "extraction_complete": False,
                    "text_delivery_complete": False, "reason": "untrusted_or_changed_snapshot"}
        return deepcopy(entry["document"]["coverage"])


def record_source_delivery(document: dict[str, Any], *, offset: int, returned_chars: int) -> dict[str, Any]:
    """Credit only the exact character interval emitted by a trusted reader."""
    with _LOCK:
        entry = _entry(document)
        if entry is None:
            return {**document, "coverage": current_document_coverage(document)}
        cov = entry["document"]["coverage"]
        total = cov["total_chars"]
        start, end = max(0, offset), min(total, offset + max(0, returned_chars))
        if end > start:
            entry["ranges"].append((start, end))
        merged: list[tuple[int, int]] = []
        for a, b in sorted(entry["ranges"]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        entry["ranges"] = merged
        delivered = bool(total and merged == [(0, total)])
        cov.update(returned_range={"start": start, "end": end}, text_delivery_complete=delivered,
                   complete=cov["extraction_complete"] and delivered)
        cov["status"] = "complete" if cov["complete"] else ("partial" if total else "blocked")
        return {**document, "coverage": deepcopy(cov)}


def documents_for_run(run_dir: str | Path) -> list[dict[str, Any]]:
    with _LOCK:
        documents = {(entry["document"]["source"], entry["document"].get("requested_url", "")): deepcopy(entry["document"])
                     for entry in _DOCUMENTS.values() if entry["owner"] == str(Path(run_dir).resolve())}
        return list(documents.values())


def document_chunk(document: dict[str, Any], *, offset: int = 0, max_chars: int = 15000,
                   deliver: bool = True) -> tuple[str, dict[str, Any], int | None]:
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 50000:
        raise ValueError("offset must be nonnegative and max_chars must be between 1 and 50000")
    if _entry(document) is None:
        raise ValueError("Source snapshot integrity check failed")
    text = Path(document["full_text_path"]).read_text(encoding="utf-8")
    if offset > len(text):
        raise ValueError("offset exceeds extracted source length")
    body = text[offset:offset + max_chars]
    updated = record_source_delivery(document, offset=offset, returned_chars=len(body)) if deliver else document
    return body, updated, offset + len(body) if offset + len(body) < len(text) else None


def document_result(payload: dict[str, Any], *, offset: int = 0, max_chars: int = 15000,
                    text_field: str = "text", deliver: bool = True) -> dict[str, Any]:
    """Fit the actual JSON envelope before crediting text as delivered."""
    import json
    from src.config.limits import TOOL_RESULT_LIMIT

    document = payload["source_document"]
    text, _, _ = document_chunk(document, offset=offset, max_chars=max_chars, deliver=False)
    payload.update(full_text_path=document["full_text_path"], next_offset=None)
    low, high = 0, len(text)
    while low < high:
        size = (low + high + 1) // 2
        candidate = with_security_warnings({**payload, text_field: text[:size]}, fields=(text_field,))
        # Leave room for source IDs added by the observation ledger.
        if len(json.dumps(candidate, ensure_ascii=False)) <= TOOL_RESULT_LIMIT - 1500:
            low = size
        else:
            high = size - 1
    if text and not low:
        raise ValueError("Source metadata exceeds the delivery limit")
    body = text[:low]
    updated = record_source_delivery(document, offset=offset, returned_chars=len(body)) if deliver else document
    payload.update({text_field: body, "source_document": updated,
                    "next_offset": offset + len(body) if offset + len(body) < document["coverage"]["total_chars"] else None,
                    "offset": offset, "truncated": len(body) < document["coverage"]["total_chars"]})
    return with_security_warnings(payload, fields=(text_field,))
