"""API error handling: map domain/port failures to ``ProblemDetail`` responses.

Cross-process errors use ``ProblemDetail`` (never a public ErrorEnvelope).
Retryability and safe messages are preserved from the source error.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ueaf.api.schemas import ProblemDetailOut
from ueaf.common.error import Retryability
from ueaf.infrastructure.db.repositories import RevisionConflict, StaleFencing
from ueaf.runtime.state_machine import StateMachineError


def _problem(
    *,
    code: str,
    category: str,
    message_safe: str,
    retryability: Retryability,
    source: str,
    object_ref: str | None = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    cause_ref: str | None = None,
    field_paths: list[str] | None = None,
) -> JSONResponse:
    body = ProblemDetailOut(
        code=code,
        category=category,
        message_safe=message_safe,
        retryability=retryability,
        source=source,
        object_ref=object_ref,
        field_paths=field_paths or [],
        correlation_refs={},
        cause_ref=cause_ref,
        observed_at=datetime.now(UTC),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StateMachineError)
    async def _state_machine(_request: Request, exc: StateMachineError) -> JSONResponse:
        return _problem(
            code=exc.code,
            category="conflict",
            message_safe=f"invalid state transition: {exc.from_phase} -> {exc.to_phase}",
            retryability="never",
            source="ueaf-runtime",
            object_ref=None,
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(RevisionConflict)
    async def _revision_conflict(_request: Request, exc: RevisionConflict) -> JSONResponse:
        return _problem(
            code="revision_conflict",
            category="conflict",
            message_safe="the object was modified concurrently; reload and retry",
            retryability="safe",
            source="ueaf-persistence",
            object_ref=exc.aggregate,
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(StaleFencing)
    async def _stale_fencing(_request: Request, exc: StaleFencing) -> JSONResponse:
        return _problem(
            code="stale_fencing_token",
            category="conflict",
            message_safe="execution lease is stale; the holder no longer owns the write",
            retryability="never",
            source="ueaf-persistence",
            object_ref=exc.aggregate,
            status_code=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(KeyError)
    async def _not_found(_request: Request, exc: KeyError) -> JSONResponse:
        return _problem(
            code="not_found",
            category="not_found",
            message_safe=str(exc) or "object not found",
            retryability="never",
            source="ueaf-runtime",
            object_ref=str(exc.args[0]) if exc.args else None,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @app.exception_handler(ValueError)
    async def _validation(_request: Request, exc: ValueError) -> JSONResponse:
        return _problem(
            code="validation_failed",
            category="validation",
            message_safe=str(exc) or "validation failed",
            retryability="never",
            source="ueaf-admission",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
