"""Share actual readonly tool observations; model reports never enter here."""

from __future__ import annotations

import hashlib
import json
import threading
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.agent.result_artifacts import save_result_parts, TOOL_RESULT_LIMIT

current_observations: ContextVar[SwarmObservations | None] = ContextVar("swarm_observations", default=None)
NON_EVIDENCE_TOOLS = frozenset({
    "bash", "read_file", "write_file", "load_skill", "edit_file",
    "web_search", "parallel_web_search", "search_symbol", "search_broker_reports",
    "get_stock_news", "get_research_reports",
    "session_search", "search_hypotheses", "qveris_search", "load_tools",
    "technical_indicators", "financial_rigor",
})


def _write_bytes(path: Path, data: bytes, root: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Observation artifact escapes its workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("An observation artifact was changed")


class SwarmObservations:
    """One run's observed results, backed by the invoking run's trusted ledger."""

    def __init__(self, ledger: Any, run_dir: Path, run_id: str) -> None:
        self.ledger = ledger
        self.run_dir = run_dir.resolve()
        self.run_id = run_id
        self.root = Path(ledger.run_dir).resolve()
        self._lock = threading.RLock()
        self._receipts: list[dict[str, Any]] = []
        self._readable: dict[str, tuple[bytes, dict[str, Any] | None, str]] = {}

    def record(self, *, tool_name: str, arguments: dict, result: str, call_id: str,
               agent_id: str, task_id: str, artifact_dir: Path) -> str:
        """Ingest the full real tool output, then expose only assigned source IDs."""
        digest = hashlib.sha256(result.encode("utf-8")).hexdigest()
        namespaced = f"swarm:{self.run_id}:{agent_id}:{task_id}:{call_id}:{digest[:12]}"
        with self._lock:
            observed = self.ledger.ingest_observation(tool_name=tool_name, arguments=arguments,
                                                       result=result, call_id=namespaced, success=True)
            sources = observed["sources"]
            folder = self.root / "artifacts" / "swarm-observations" / self.run_id / digest
            parts = save_result_parts(result, folder, self.root)
            try:
                payload = json.loads(result)
            except (ValueError, TypeError):
                payload = None
            documents = []
            if isinstance(payload, dict):
                raw_docs = payload.get("source_documents") or []
                if isinstance(payload.get("source_document"), dict):
                    raw_docs = [payload["source_document"], *raw_docs]
                for item in raw_docs:
                    if not isinstance(item, dict):
                        continue
                    document = deepcopy(item)
                    for key in ("artifact_path", "text_path", "full_text_path"):
                        if not item.get(key):
                            continue
                        original = Path(item[key]).resolve()
                        # A reader cannot smuggle arbitrary host files into shared evidence.
                        if not original.is_relative_to(artifact_dir.resolve()) or not original.is_file():
                            document.pop(key, None)
                            continue
                        data = original.read_bytes()
                        file_digest = hashlib.sha256(data).hexdigest()
                        saved = folder / "documents" / (file_digest + original.suffix)
                        _write_bytes(saved, data, self.root)
                        document[key] = str(saved)
                    documents.append(document)
            receipt = {"swarm_run_id": self.run_id, "agent_id": agent_id, "task_id": task_id,
                       "call_id": namespaced, "tool": tool_name, "sha256": digest, "parts": parts,
                       "source_ids": [source["id"] for source in sources], "sources": sources,
                       "evidence_count": observed["evidence_count"], "source_documents": documents}
            self._receipts.append(receipt)
            self.ledger.record_shared_observation(receipt)
            self._persist()
            if isinstance(payload, dict):
                # Never retain a tool/model-supplied source ID as a parent source ID.
                payload.pop("_sources", None)
                if sources:
                    payload["_sources"] = sources
                payload["_observation"] = {"call_id": namespaced, "sha256": digest,
                                           "source_ids": receipt["source_ids"], "parts": parts}
                return json.dumps(payload, ensure_ascii=False)
            return result

    def prepare(self, artifact_dir: Path) -> str:
        """Copy shared results into this worker's sandbox, without widening it."""
        with self._lock:
            receipts = deepcopy(self._receipts)
            for receipt in receipts:
                folder = artifact_dir / "shared-observations" / receipt["sha256"]
                for key, paths in (("parts", receipt["parts"]),):
                    local_paths = []
                    for value in paths:
                        original = Path(value)
                        data = original.read_bytes()
                        local = folder / original.name
                        _write_bytes(local, data, artifact_dir)
                        self._readable[str(local.resolve())] = (data, None, receipt["tool"])
                        local_paths.append(str(local))
                    receipt[key] = local_paths
                for document in receipt["source_documents"]:
                    for key in ("artifact_path", "text_path", "full_text_path"):
                        if not document.get(key):
                            continue
                        original = Path(document[key])
                        data = original.read_bytes()
                        local = folder / "documents" / original.name
                        _write_bytes(local, data, artifact_dir)
                        self._readable[str(local.resolve())] = (data, document, receipt["tool"])
                        document[key] = str(local)
            if not receipts:
                return ""
            return ("\n\n## Collected tool observations\nThese are observed reads, not independent truth. "
                    "Use only the assigned source IDs. Read the listed parts with read_file before relying "
                    "on details omitted by upstream prose. Model reports and their invented refs are not sources.\n"
                    "For long text use read_file(offset=0,max_chars=7000), follow next_offset until null.\n"
                    + json.dumps(receipts, ensure_ascii=False))

    def trusted_read(self, arguments: dict, result: str, *, call_id: str = "shared-read") -> bool:
        """Credit only a real read of the unmodified server-copied evidence."""
        try:
            payload = json.loads(result)
            path = str(Path(payload.get("path") or arguments.get("path") or "").resolve())
            with self._lock:
                saved = self._readable.get(path)
            if saved is None:
                return False
            data, document, origin_tool = saved
            if origin_tool in NON_EVIDENCE_TOOLS:
                return False
            content = payload.get("content")
            offset = payload.get("offset", 0)
            if not isinstance(content, str) or not content or type(offset) is not int or offset < 0:
                return False
            saved_text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if len(result) > TOOL_RESULT_LIMIT or content != saved_text[offset:offset + len(content)]:
                return False
            if document is not None and path in {document.get("text_path"), document.get("full_text_path")}:
                from src.tools.source_documents import record_source_delivery
                record_source_delivery(document, offset=offset, returned_chars=len(content))
                source = document.get("source") or document.get("url") or ""
                remote = source.startswith(("http://", "https://"))
                observed = {"status": "ok", "content" if remote else "text": content,
                            "url" if remote else "file": source if remote else Path(source).name}
                if not remote:
                    observed["source_url"] = "doc://" + Path(source).as_posix()
                self.ledger.ingest_observation(
                    tool_name="read_url" if remote else "read_document", arguments=arguments,
                    result=json.dumps(observed, ensure_ascii=False), success=True,
                    call_id=f"swarm:{self.run_id}:read_file:{call_id}:{hashlib.sha256(path.encode()).hexdigest()[:12]}:{offset}",
                )
            return True
        except (ValueError, TypeError, OSError):
            return False

    def _persist(self) -> None:
        path = self.run_dir / "observations.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._receipts, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
