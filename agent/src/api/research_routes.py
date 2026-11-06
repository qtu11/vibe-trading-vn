"""Authenticated, fixed read-only research calls shared with agent/MCP tools."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from src.api.security import require_auth, require_settings_write_auth
from src.tools.crypto_derivatives_tool import CryptoDerivativesTool
from src.tools.vietnam_research_tool import VietnamResearchTool
from src.tools.vietnam_comparables_tool import VietnamComparablesTool
from src.tools.vietnam_dcf import build_vietnam_dcf

_LOG = logging.getLogger(__name__)


class VietnamResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(strict=True, pattern=r"^[A-Z0-9]{1,12}\.VN$", max_length=15)]
    as_of: Annotated[str, Field(strict=True, max_length=64)] | None = None
    period: Literal["quarter", "annual"] = "quarter"
    consolidation: Literal["consolidated", "separate"] = "consolidated"
    offset: Annotated[int, Field(strict=True, ge=0, le=1000)] = 0

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("as_of must include a timezone")
        return value


class _CryptoResearchBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: Annotated[str, Field(strict=True, pattern=r"^[A-Z0-9]{1,30}-USDT-PERP$", max_length=40)]
    metric: Literal["open_interest", "funding"] = "open_interest"
    period: Literal["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"] = "1h"
    limit: Annotated[int, Field(strict=True, ge=2, le=100)] = 30


class CryptoResearchRequest(_CryptoResearchBase):
    mode: Literal["live", "archive"] = "live"
    as_of: Annotated[str, Field(strict=True, max_length=64)] | None = None

    @model_validator(mode="after")
    def archive_cutoff(self):
        if self.mode == "archive":
            if self.as_of is None:
                raise ValueError("archive requires as_of with a timezone")
            parsed = datetime.fromisoformat(self.as_of.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("as_of must include a timezone")
        elif self.as_of is not None:
            raise ValueError("as_of is only supported in archive mode")
        return self


class CryptoCaptureRequest(_CryptoResearchBase):
    mode: Literal["capture"] = "capture"


class VietnamComparablesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict
    offset: Annotated[int, Field(strict=True, ge=0, le=12)] = 0


def _execute(tool, payload: BaseModel) -> dict:
    try:
        result = json.loads(tool.execute(**payload.model_dump(exclude_none=True)))
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ValueError("Invalid research result envelope")
        return result
    except Exception:
        # Tool-level argument/provider errors already have a safe envelope. Do
        # not disclose paths or arbitrary provider exception text on this API.
        _LOG.error("Research tool failed unexpectedly: %s", tool.name)
        raise HTTPException(503, detail={"code": "RESEARCH_UNAVAILABLE", "message": "Research is unavailable; no result was inferred"}) from None


def register_research_routes(app: FastAPI) -> None:
    read = [Depends(require_auth)]

    @app.post("/api/research/vietnam", dependencies=read)
    def vietnam(payload: VietnamResearchRequest):
        return _execute(VietnamResearchTool(), payload)

    @app.post("/api/research/crypto", dependencies=read)
    def crypto(payload: CryptoResearchRequest):
        return _execute(CryptoDerivativesTool(), payload)

    @app.post("/api/research/crypto/captures", dependencies=[Depends(require_settings_write_auth)])
    def crypto_capture(payload: CryptoCaptureRequest):
        return _execute(CryptoDerivativesTool(), payload)

    @app.post("/api/research/vietnam/comparables", dependencies=read)
    def vietnam_comparables(payload: VietnamComparablesRequest):
        return _execute(VietnamComparablesTool(), payload)

    @app.post("/api/research/vietnam/dcf", dependencies=read)
    def vietnam_dcf(payload: dict):
        try:
            return build_vietnam_dcf(payload)
        except ValidationError as exc:
            errors = [{"loc": ["body", *item["loc"]], "msg": item["msg"]}
                      for item in exc.errors(include_input=False, include_context=False)[:8]]
            raise HTTPException(422, detail=errors) from None
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(422, detail={"code": "INVALID_VN_DCF", "message": str(exc)}) from None
        except Exception:
            _LOG.error("VN DCF research unavailable")
            raise HTTPException(503, detail={"code": "RESEARCH_UNAVAILABLE", "message": "VN valuation research is unavailable"}) from None

    def calculate(builder, payload, code):
        try:
            return builder(payload)
        except ValidationError as exc:
            errors = [{"loc": ["body", *item["loc"]], "msg": item["msg"]}
                      for item in exc.errors(include_input=False, include_context=False)[:8]]
            raise HTTPException(422, detail=errors) from None
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(422, detail={"code": code, "message": str(exc)}) from None
        except Exception:
            _LOG.error("Bounded research unavailable: %s", code)
            raise HTTPException(503, detail={"code": "RESEARCH_UNAVAILABLE", "message": "Research calculation is unavailable"}) from None

    @app.post("/api/research/vietnam/reverse-dcf", dependencies=read)
    def vietnam_reverse_dcf(payload: dict):
        from src.tools.vietnam_reverse_dcf import build_vietnam_reverse_dcf
        return calculate(build_vietnam_reverse_dcf, payload, "INVALID_VN_REVERSE_DCF")

    @app.post("/api/research/crypto/basis", dependencies=read)
    def crypto_basis(payload: dict):
        from src.tools.crypto_basis import build_crypto_basis
        return calculate(build_crypto_basis, payload, "INVALID_CRYPTO_BASIS")
