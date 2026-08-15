"""ContextBuildPort reference implementation (Module 04 owns ContextManifest).

ACL filtering must precede relevance ranking (RAG-001); Module 03/05 only
validate and map, never rewrite the manifest. The builder conforms to the core
``ContextBuildPort.build(request) -> PortResult[ContextManifest]`` signature;
sources and the principal scope are supplied at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.ports import ContextBuildRequest, ContextManifest, PortResult, Success


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
    ) -> None:
        self._sources = list(sources or [])
        self._principal_scopes = tuple(principal_scopes)
        self._max_snippets = max_snippets
        self._producer_version = producer_version

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

    @property
    def packed_source_count(self) -> int:
        return len(self._sources)
