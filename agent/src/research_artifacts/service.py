"""Fixed server-side research execution, revision comparison and review.

This is a snapshot of the returned deterministic page, not an AI narrative or
an independently verified financial report. Caller-supplied results are never
accepted. A failed refresh leaves every previous revision untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Callable
import uuid

from src.research_artifacts.store import (
    ArtifactError, ResearchArtifactStore, _bounded_integer, canonical, digest, utc_timestamp, validate_idempotency_key,
)

_KINDS = {"vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis"}


def _producer(kind: str) -> dict:
    modules = ["src.research_artifacts.service"]
    if kind != "crypto_basis":
        modules += ["src.tools.local_financial_statements"]
    if kind == "vietnam":
        modules += ["src.tools.vietnam_research_tool", "src.tools._result_paging", "backtest.loaders.local_loader"]
    elif kind == "vietnam_comparables":
        modules += ["src.tools.vietnam_comparables_tool", "src.tools.vietnam_comparables",
                    "src.tools._result_paging", "src.quantlib.valuation.comps", "src.quantlib.valuation.contracts"]
    elif kind in {"vietnam_dcf", "vietnam_reverse_dcf"}:
        modules += ["src.tools.vietnam_dcf", "src.tools.vietnam_comparables",
                    "src.quantlib.valuation.dcf", "src.quantlib.valuation.contracts"]
        if kind == "vietnam_reverse_dcf":
            modules += ["src.tools.vietnam_reverse_dcf"]
    else:
        modules += ["src.tools.crypto_basis", "src.quantlib.fixedincome"]
    hashes = {}
    for name in modules:
        module = importlib.import_module(name)
        hashes[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {"execution": "server_deterministic_engine", "source_sha256": hashes,
            "hash_scope": "Named producer modules only; dependency versions and external evidence authenticity are not attested"}


def _projections(kind: str, request: dict, result: dict) -> tuple[dict, dict]:
    if kind == "vietnam":
        company = result["data"][request["code"]]
        periods = company["periods"]
        sources = {"metadata": {key: value for key, value in company.items() if key not in {"periods", "as_of"}},
                   "periods": [{"period_start": row["period_start"], "period_end": row["period_end"],
                                "evidence": row["evidence"]} for row in periods]}
        facts = {str((row["period_start"], row["period_end"])):
                 {name: {key: value for key, value in fact.items() if key != "evidence"}
                  for name, fact in row["inputs"].items()} for row in periods}
        return sources, facts
    if kind == "vietnam_comparables":
        payload = request["payload"]
        companies = [payload["target"], *payload["peers"]]
        return ({company["symbol"]: {key: company[key] for key in ("financial_evidence", "price_evidence")}
                 for company in companies},
                {company["symbol"]: {key: value for key, value in company.items()
                                     if key not in {"financial_evidence", "price_evidence"}} for company in companies})
    if kind == "vietnam_reverse_dcf":
        return {"evidence": request["dcf"]["evidence"], "price_evidence": request["price_evidence"]}, {
            **{key: value for key, value in request.items() if key not in {"dcf", "price_evidence"}},
            "dcf": {key: value for key, value in request["dcf"].items() if key != "evidence"}}
    if kind == "crypto_basis":
        def quote_source(quote):
            return {key: quote[key] for key in ("venue", "instrument_id", "event_time", "available_at", "source_ref")}
        return {"spot": quote_source(request["spot"]), "futures": [quote_source(row) for row in request["futures"]]}, request
    return {"evidence": request["evidence"]}, {key: value for key, value in request.items() if key != "evidence"}


def _scope(kind: str, request: dict) -> dict:
    if kind == "vietnam":
        return {key: request[key] for key in ("code", "period", "consolidation", "offset")}
    if kind == "vietnam_comparables":
        payload = request["payload"]
        return {"symbol": payload["target"]["symbol"], "period_start": payload["period_start"],
                "period_end": payload["period_end"], "consolidation": payload["consolidation"], "offset": request["offset"]}
    if kind == "crypto_basis":
        return {"base": request["base"], "quote": request["quote"]}
    valuation = request["dcf"] if kind == "vietnam_reverse_dcf" else request
    return {"symbol": valuation["symbol"], "consolidation": valuation["consolidation"]}


def _flatten(value: object, path: str = "") -> dict:
    """JSON Pointer leaves, preserving empty collections and null vs zero."""
    if isinstance(value, dict) and value:
        result = {}
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            result.update(_flatten(child, path + "/" + escaped))
        return result
    if isinstance(value, list) and value:
        result = {}
        for index, child in enumerate(value):
            result.update(_flatten(child, path + "/" + str(index)))
        return result
    return {path or "/": value}


def _affected_metrics(before: dict, after: dict) -> list[dict]:
    if before["kind"] != "vietnam":
        return []
    code = before["request"]["code"]
    old_rows = {(row["period_start"], row["period_end"]): row for row in before["result"]["data"][code]["periods"]}
    new_rows = {(row["period_start"], row["period_end"]): row for row in after["result"]["data"][code]["periods"]}

    def bound_input(row, name):
        fact = row["inputs"].get(name)
        if fact is None:
            return None
        evidence = {item["id"]: {key: value for key, value in item.items() if key != "id"} for item in row["evidence"]}
        return dict(fact, evidence=[evidence.get(item) for item in fact["evidence"]])

    affected = []
    for period in sorted(old_rows.keys() | new_rows.keys(), key=str):
        old, new = old_rows.get(period), new_rows.get(period)
        if old is None or new is None:
            affected.append({"symbol": code, "period_start": period[0], "period_end": period[1],
                             "metric": "*", "changed_inputs": [], "reason": "period_added_or_removed"})
            continue
        changed = {name for name in old["inputs"].keys() | new["inputs"].keys()
                   if canonical(bound_input(old, name)) != canonical(bound_input(new, name))}
        metrics = dict(old["metrics"], **new["metrics"])
        impacted = set()
        while True:
            following = {name for name, metric in metrics.items() if set(metric["inputs"]) & (changed | impacted)}
            if following <= impacted:
                break
            impacted |= following

        def leaf_dependencies(name, visited=None):
            visited = set() if visited is None else visited
            if name in visited:
                return set()
            if name not in metrics:
                return {name}
            result = set()
            for dependency in metrics[name]["inputs"]:
                result |= leaf_dependencies(dependency, visited | {name})
            return result

        for name in sorted(impacted):
            affected.append({"symbol": code, "period_start": period[0], "period_end": period[1], "metric": name,
                             "changed_inputs": sorted(changed & leaf_dependencies(name)),
                             "reason": "recorded_input_or_its_evidence_changed"})
    return affected


class ResearchArtifactService:
    def __init__(self, store: ResearchArtifactStore | None = None, *, clock: Callable[[], datetime] | None = None):
        self.store = store if store is not None else ResearchArtifactStore()
        self.clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    def _normalize(self, kind: str, request: dict) -> dict:
        if kind not in _KINDS or not isinstance(request, dict):
            raise ArtifactError("INVALID_ARGUMENT", "Unsupported research kind or request")
        try:
            if len(canonical(request).encode("utf-8")) > 64_000:
                raise ValueError
            if kind == "vietnam":
                from src.tools.local_financial_statements import _timestamp
                if request.keys() - {"code", "as_of", "period", "consolidation", "offset"}:
                    raise ValueError
                code = request.get("code")
                if not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{1,12}\.VN", code) is None:
                    raise ValueError
                normalized = {"code": code, "period": request.get("period", "quarter"),
                              "consolidation": request.get("consolidation", "consolidated"), "offset": request.get("offset", 0),
                              "as_of": _timestamp(request["as_of"], "as_of").isoformat().replace("+00:00", "Z")
                              if request.get("as_of") is not None else utc_timestamp(self.clock())}
                if normalized["period"] not in {"quarter", "annual"} or normalized["consolidation"] not in {"consolidated", "separate"}:
                    raise ValueError
                _bounded_integer(normalized["offset"], 0, 1000, "offset")
            elif kind == "vietnam_comparables":
                from src.tools.vietnam_comparables import VietnamComparablesRequest
                if request.keys() - {"payload", "offset"}:
                    raise ValueError
                normalized = {"payload": VietnamComparablesRequest.model_validate(request["payload"]).model_dump(),
                              "offset": request.get("offset", 0)}
                _bounded_integer(normalized["offset"], 0, 12, "offset")
            elif kind == "vietnam_dcf":
                from src.tools.vietnam_dcf import VietnamDCFRequest
                normalized = VietnamDCFRequest.model_validate(request).model_dump()
            elif kind == "vietnam_reverse_dcf":
                from src.tools.vietnam_reverse_dcf import VietnamReverseDCFRequest
                normalized = VietnamReverseDCFRequest.model_validate(request).model_dump()
            else:
                from src.tools.crypto_basis import CryptoBasisRequest
                normalized = CryptoBasisRequest.model_validate(request).model_dump(mode="json")
            if len(canonical(normalized).encode("utf-8")) > 64_000:
                raise ValueError
        except ArtifactError:
            raise
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            raise ArtifactError("INVALID_ARGUMENT", "Research request is invalid; no revision was saved") from None
        return normalized

    def _calculate(self, kind: str, normalized: dict) -> dict:
        try:
            if kind == "vietnam":
                from src.tools.vietnam_research_tool import VietnamResearchTool
                result = json.loads(VietnamResearchTool().execute(**normalized))
            elif kind == "vietnam_comparables":
                from src.tools.vietnam_comparables_tool import VietnamComparablesTool
                result = json.loads(VietnamComparablesTool().execute(**normalized))
            elif kind == "vietnam_dcf":
                from src.tools.vietnam_dcf import build_vietnam_dcf
                result = build_vietnam_dcf(normalized)
            elif kind == "vietnam_reverse_dcf":
                from src.tools.vietnam_reverse_dcf import build_vietnam_reverse_dcf
                result = build_vietnam_reverse_dcf(normalized)
            else:
                from src.tools.crypto_basis import build_crypto_basis
                result = build_crypto_basis(normalized)
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            raise ArtifactError("INVALID_ARGUMENT", "Research calculation failed; no revision was saved") from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ArtifactError("RESEARCH_FAILED", "Research execution failed; no revision was saved")
        if len(canonical(result).encode("utf-8")) > 64_000:
            raise ArtifactError("ARTIFACT_TOO_LARGE", "Research result exceeds the snapshot bound")
        return result

    def _manifest(self, kind: str, normalized: dict, result: dict, producer: dict, parent_revision_id: str | None) -> dict:
        sources, facts = _projections(kind, normalized, result)
        manifest = {
            "schema_version": 1, "revision_id": "rr_" + uuid.uuid4().hex, "kind": kind,
            "created_at": utc_timestamp(self.clock()), "parent_revision_id": parent_revision_id,
            "scope": _scope(kind, normalized), "request": normalized, "result": result, "producer": producer,
            "content_scope": {"vietnam": "one_returned_research_page", "vietnam_comparables": "one_returned_research_page",
                              "vietnam_dcf": "one_bounded_dcf_scenario", "vietnam_reverse_dcf": "one_bounded_reverse_dcf_scenario",
                              "crypto_basis": "one_supplied_basis_curve"}[kind],
            "verification_status": "user_supplied_unverified",
            "hashes": {"request_sha256": digest(normalized), "result_sha256": digest(result),
                       "producer_sha256": digest(producer), "source_sha256": digest(sources), "facts_sha256": digest(facts)},
            "limitations": [
                "This stores an actual deterministic server execution; it is not an AI-authored report or independent source verification.",
                "Only the returned page or bounded scenario is saved; paging does not imply complete financial-history coverage.",
                "A review is a self-reported operator acknowledgment of this exact revision; evidence remains unverified.",
                "Integrity hashes are not an authenticity signature, a complete environment lockfile, or proof of source publication time.",
                "Failed execution appends no replacement revision; existing revisions retain their original timestamps and content.",
            ],
        }
        return manifest

    def _resume(self, receipt: dict) -> dict:
        if receipt["status"] == "succeeded":
            # Result/input bytes remain immutable. Current review history is
            # deliberately read fresh rather than replaying an old HTTP body.
            return self.store.get_revision(receipt["revision_id"])
        if receipt["status"] == "failed":
            error = receipt["error"]
            raise ArtifactError(error["code"], error["message"], receipt=receipt)
        raise ArtifactError("RESEARCH_ATTEMPT_IN_FLIGHT", "Research attempt may be running or interrupted; it was not executed again", receipt=receipt)

    def _uncertain(self, attempt: dict) -> dict:
        try:
            receipt = self.store.get_attempt(attempt["attempt_id"])
        except Exception:
            receipt = attempt
        if receipt["status"] != "in_flight_unknown":
            return self._resume(receipt)
        raise ArtifactError("RESEARCH_ATTEMPT_UNCERTAIN", "Attempt completion could not be confirmed; inspect its history before another save", receipt=receipt) from None

    def execute_and_save(self, kind: str, request: dict, *, parent_revision_id: str | None = None,
                         idempotency_key: str | None = None) -> dict:
        validate_idempotency_key(idempotency_key)
        try:
            if kind not in _KINDS or not isinstance(request, dict) or len(canonical(request).encode("utf-8")) > 64_000:
                raise ValueError
            caller_hash = digest({"kind": kind, "request": request, "parent_revision_id": parent_revision_id})
        except (ValueError, TypeError, RecursionError):
            raise ArtifactError("INVALID_ARGUMENT", "Research request must be a supported bounded finite JSON object") from None
        existing = self.store.lookup_attempt(idempotency_key, caller_hash)
        if existing is not None:
            return self._resume(existing)
        if parent_revision_id is not None:
            self.store.get_revision(parent_revision_id)
        normalized = self._normalize(kind, request)
        attempt, acquired = self.store.reserve_attempt(
            kind=kind, request=normalized, scope=_scope(kind, normalized), caller_hash=caller_hash,
            parent_revision_id=parent_revision_id, idempotency_key=idempotency_key, clock=self.clock,
        )
        if not acquired:
            return self._resume(attempt)
        stage = "producer"
        try:
            producer = _producer(kind)
            stage = "engine"
            result = self._calculate(kind, normalized)
            stage = "manifest"
            manifest = self._manifest(kind, normalized, result, producer, parent_revision_id)
        except Exception as exc:
            error = {"code": exc.code if isinstance(exc, ArtifactError) else "RESEARCH_EXECUTION_FAILED",
                     "message": str(exc) if isinstance(exc, ArtifactError) else "Research execution failed; no replacement revision was saved",
                     "stage": stage, "exception_type": type(exc).__name__}
            try:
                receipt = self.store.finish_attempt_failure(attempt["attempt_id"], error, clock=self.clock)
            except Exception:
                return self._uncertain(attempt)
            return self._resume(receipt)
        try:
            return self.store.finish_attempt_success(attempt["attempt_id"], manifest, clock=self.clock)
        except Exception:
            return self._uncertain(attempt)

    def list_revisions(self, *, kind: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        return self.store.list_revisions(kind=kind, limit=limit, offset=offset)

    def list_attempts(self, *, kind: str | None = None, parent_revision_id: str | None = None,
                      idempotency_key: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        return self.store.list_attempts(kind=kind, parent_revision_id=parent_revision_id,
                                        idempotency_key=idempotency_key, limit=limit, offset=offset)

    def get_revision(self, revision_id: str) -> dict:
        return self.store.get_revision(revision_id)

    def review_revision(self, revision_id: str, *, decision: str, note: str, reviewer: str) -> dict:
        return self.store.review_revision(revision_id, decision=decision, note=note, reviewer=reviewer, clock=self.clock)

    def diff_revisions(self, before_id: str, after_id: str, *, limit: int = 100) -> dict:
        _bounded_integer(limit, 1, 200, "limit")
        before, after = self.get_revision(before_id), self.get_revision(after_id)
        if before["kind"] != after["kind"] or before["scope"] != after["scope"]:
            raise ArtifactError("INCOMPATIBLE_SCOPE", "Revision comparison requires the same research scope")
        old, new = _flatten(before["result"]), _flatten(after["result"])
        changes = []
        for path in sorted(old.keys() | new.keys()):
            if path in old and path in new and canonical(old[path]) == canonical(new[path]):
                continue
            item = {"path": path, "change": "added" if path not in old else "removed" if path not in new else "changed",
                    "before": old.get(path), "after": new.get(path)}
            changes.append(item)
        return {"before_revision_id": before_id, "after_revision_id": after_id, "compatible_scope": True,
                **{name + "_changed": before["hashes"][key] != after["hashes"][key]
                   for name, key in (("request", "request_sha256"), ("producer", "producer_sha256"),
                                     ("source", "source_sha256"), ("facts", "facts_sha256"), ("result", "result_sha256"))},
                "total_changes": len(changes), "changes": changes[:limit], "truncated": len(changes) > limit,
                "affected_metrics": _affected_metrics(before, after),
                "dependency_scope": "VN recorded ratio inputs and their evidence only; no general narrative-claim graph or selective report regeneration",
                "verification_status": "user_supplied_unverified"}
