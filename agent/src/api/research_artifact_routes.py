"""Local revision snapshots; callers supply inputs, never pre-certified results."""

import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from src.api.security import require_auth, require_settings_write_auth

_LOG = logging.getLogger(__name__)
Kind = Literal["vietnam", "vietnam_comparables", "vietnam_dcf", "vietnam_reverse_dcf", "crypto_basis"]
RevisionId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,100}$")]
IdempotencyKey = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{8,128}$")]


class SaveResearchRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    request: dict
    parent_revision_id: RevisionId | None = None
    idempotency_key: IdempotencyKey | None = None


class ReviewResearchRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["acknowledged", "changes_requested"]
    note: Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
    reviewer: Annotated[str, Field(strict=True, min_length=1, max_length=120)]


def register_research_artifact_routes(app: FastAPI, service=None) -> None:
    # Lazy construction lets read-only starts avoid touching a runtime file.
    def current():
        if service is not None:
            return service
        from src.research_artifacts.service import ResearchArtifactService
        return ResearchArtifactService()

    def invoke(method, *args, **kwargs):
        from src.research_artifacts.store import ArtifactError
        try:
            return getattr(current(), method)(*args, **kwargs)
        except ArtifactError as exc:
            code = exc.code
            conflicts = {
                "INCOMPATIBLE_SCOPE", "ARTIFACT_INTEGRITY_ERROR", "ARTIFACT_STORE_INVALID",
                "REVISION_SCOPE_MISMATCH", "ARTIFACT_CLOCK_REGRESSION",
                "IDEMPOTENCY_CONFLICT", "RESEARCH_ATTEMPT_IN_FLIGHT", "RESEARCH_ATTEMPT_UNCERTAIN",
            }
            status = 404 if code == "REVISION_NOT_FOUND" else 409 if code in conflicts else 503 if code == "RESEARCH_EXECUTION_FAILED" else 422
            detail = {"code": code, "message": str(exc)}
            if getattr(exc, "receipt", None) is not None:
                detail["receipt"] = exc.receipt
            raise HTTPException(status, detail=detail) from None
        except Exception:
            _LOG.error("Research revision operation unavailable: %s", method)
            raise HTTPException(503, detail={"code": "RESEARCH_ARTIFACT_UNAVAILABLE", "message": "Research revision storage is unavailable"}) from None

    @app.post("/api/research/artifacts", dependencies=[Depends(require_settings_write_auth)])
    def save(payload: SaveResearchRevision):
        options = {"parent_revision_id": payload.parent_revision_id}
        if payload.idempotency_key is not None:
            options["idempotency_key"] = payload.idempotency_key
        return invoke("execute_and_save", payload.kind, payload.request, **options)

    @app.get("/api/research/artifacts", dependencies=[Depends(require_auth)])
    def listing(kind: Kind | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return invoke("list_revisions", kind=kind, limit=limit, offset=offset)

    @app.get("/api/research/artifacts/attempts", dependencies=[Depends(require_auth)])
    def attempts(kind: Kind | None = None, parent_revision_id: RevisionId | None = None,
                 idempotency_key: IdempotencyKey | None = None,
                 limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000)):
        return invoke("list_attempts", kind=kind, parent_revision_id=parent_revision_id,
                      idempotency_key=idempotency_key, limit=limit, offset=offset)

    @app.get("/api/research/artifacts/{revision_id}", dependencies=[Depends(require_auth)])
    def get(revision_id: RevisionId):
        return invoke("get_revision", revision_id)

    @app.get("/api/research/artifacts/{revision_id}/report", dependencies=[Depends(require_auth)])
    def report(revision_id: RevisionId):
        revision = invoke("get_revision", revision_id)
        from src.research_artifacts.report import ReportExportError, render_revision_markdown
        try:
            rendered = render_revision_markdown(revision)
        except ReportExportError as exc:
            raise HTTPException(413 if exc.code == "REPORT_TOO_LARGE" else 422, detail={"code": exc.code, "message": str(exc)}) from None
        except Exception:
            _LOG.error("Research report export unavailable")
            raise HTTPException(503, detail={"code": "RESEARCH_REPORT_UNAVAILABLE", "message": "Research report export is unavailable"}) from None
        return Response(content=rendered, media_type="text/markdown; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="research-{revision_id}.md"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    @app.get("/api/research/artifacts/{revision_id}/diff", dependencies=[Depends(require_auth)])
    def diff(revision_id: RevisionId, before: RevisionId, limit: int = Query(100, ge=1, le=200)):
        return invoke("diff_revisions", before, revision_id, limit=limit)

    @app.post("/api/research/artifacts/{revision_id}/reviews", dependencies=[Depends(require_settings_write_auth)])
    def review(revision_id: RevisionId, payload: ReviewResearchRevision):
        return invoke("review_revision", revision_id, **payload.model_dump())
