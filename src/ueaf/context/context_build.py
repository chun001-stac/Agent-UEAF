"""ContextBuildPort reference implementation (Module 04 owns ContextManifest).

ACL filtering must precede relevance ranking (RAG-001); Module 03/05 only
validate and map, never rewrite the manifest. The builder conforms to the core
``ContextBuildPort.build(request) -> PortResult[ContextManifest]`` signature;
sources and the principal scope are supplied at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.ports import (
    ContextBuildRequest,
    ContextManifest,
    PortError,
    PortResult,
    Rejected,
    Success,
)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A source that may be packed into a ContextManifest."""

    source_ref: str
    source_version: str
    content_digest: str
    allowed_scopes: tuple[str, ...]
    trust_label: str
    summary_ref: str | None = None
    snippet: str | None = None


class ContextBuilder:
    """Deterministic context packer: ACL first, then selection, then omissions."""

    def __init__(
        self,
        *,
        sources: list[SourceDocument] | None = None,
        principal_scopes: tuple[str, ...] = (),
        max_snippets: int = 8,
        producer_version: str = "0.1.0",
        max_manifest_tokens: int = 10_000,
        critical_reserve_tokens: int = 512,
    ) -> None:
        self._sources = list(sources or [])
        self._principal_scopes = tuple(principal_scopes)
        self._max_snippets = max_snippets
        self._producer_version = producer_version
        self._max_manifest_tokens = max_manifest_tokens
        self._critical_reserve_tokens = critical_reserve_tokens
        self._superseded_refs: dict[str, str] = {}  # correction source -> superseded source

    def build(self, request: ContextBuildRequest) -> PortResult[ContextManifest]:
        # ACL before relevance: sources outside the principal scope are omitted.
        allowed = [
            source
            for source in self._sources
            if set(source.allowed_scopes).intersection(self._principal_scopes)
        ]
        # Deterministic selection: trust label then source order.
        allowed.sort(key=lambda s: (s.trust_label, s.source_ref))
        selected = allowed[: self._max_snippets]

        # CTX-003: critical reserve + prompt control reserve must not be crowded
        # out. Return a deterministic budget failure instead of a plausible
        # manifest; the model is never called.
        required = self._estimate_tokens(selected) + self._critical_reserve_tokens
        if required > self._max_manifest_tokens:
            return Rejected(
                PortError(
                    code="context_budget_exceeded",
                    category="budget",
                    retryability="never",
                    certainty="not_executed",
                    message_ref=None,
                    provider_error_ref=None,
                    observed_at=request.deadline_at,
                    details_schema_ref="schema://context-budget-failure/1.0.0",
                )
            )

        manifest_id = new_object_id("context")
        integrity = sha256_hex(
            "|".join(
                f"{source.source_ref}@{source.source_version}:{source.content_digest}"
                for source in selected
            )
        )
        manifest = ContextManifest(
            context_manifest_id=manifest_id,
            run_id=request.run_id,
            schema_ref="schema://context-manifest/1.0.0",
            evidence_pack_refs=tuple(source.source_ref for source in selected),
            integrity_ref=integrity,
        )
        return Success(manifest)

    def record_superseded(self, correction_ref: str, superseded_ref: str) -> None:
        """Record that a newer correction supersedes an older summary (CTX-004)."""
        self._superseded_refs[correction_ref] = superseded_ref

    @property
    def superseded_refs(self) -> dict[str, str]:
        return dict(self._superseded_refs)

    def _estimate_tokens(self, selected: list[SourceDocument]) -> int:
        return 64 + sum(24 + len(source.snippet or "") for source in selected)

    @property
    def packed_source_count(self) -> int:
        return len(self._sources)
