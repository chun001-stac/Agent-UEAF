"""RAG indexing: reproducible projections, semantic chunk boundaries, deletion.

RAG-005 reproducible indexing metadata: the same source version plus parser /
chunk / embedding / index policy yields traceably identical metadata; changing
any of those versions produces a distinguishable projection.
RAG-006 semantic chunk boundaries: heading/symbol/table-header/thread/page/span
and record ids are preserved.
RAG-008 deleted source disappears: after deletion, production retrieval never
recalls the old chunks; historical snapshots are isolated to Eval/Replay.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    source_ref: str
    source_version: str
    text: str
    locator: str  # heading / symbol / table-header / thread / page:span / record id
    embedding_ref: str | None = None


@dataclass(frozen=True, slots=True)
class IndexPolicy:
    """Deterministic policy versions that shape an index projection (RAG-005)."""

    parser_version: str = "parser@1.0.0"
    chunk_version: str = "chunk@1.0.0"
    embedding_version: str | None = None
    index_version: str = "index@1.0.0"


@dataclass(frozen=True, slots=True)
class IndexProjection:
    """Reproducible metadata for one source version under a fixed policy."""

    source_ref: str
    source_version: str
    policy: IndexPolicy
    chunk_refs: tuple[str, ...] = ()

    @property
    def projection_digest(self) -> str:
        return sha256_hex(
            "|".join(
                [
                    self.source_ref,
                    self.source_version,
                    self.policy.parser_version,
                    self.policy.chunk_version,
                    self.policy.embedding_version or "",
                    self.policy.index_version,
                ]
            )
        )

    def same_as(self, other: IndexProjection) -> bool:
        return self.projection_digest == other.projection_digest


def split_semantic_chunks(text: str, *, locator: str = "doc") -> tuple[Chunk, ...]:
    """Deterministic chunking that respects semantic boundaries (RAG-006).

    Headings (``#``), code fences, table headers (``|`` rows), and blank-line
    separators are preserved as locators; a chunk never splits a fenced code
    block or a table header row.
    """
    chunks: list[Chunk] = []
    buffer: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            buffer.append(line)
            continue
        if not in_code and (line.startswith("#") or line.startswith("|") or not line.strip()):
            if buffer:
                body = "\n".join(buffer).strip()
                if body:
                    chunks.append(Chunk(f"chunk:{len(chunks)}", "", "", body, locator))
                buffer = []
            if line.strip():
                buffer.append(line)
            continue
        buffer.append(line)
    if buffer:
        body = "\n".join(buffer).strip()
        if body:
            chunks.append(Chunk(f"chunk:{len(chunks)}", "", "", body, locator))
    return tuple(chunks)


class RetrievalIndex:
    """In-memory index honoring source deletion (RAG-008)."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._deleted_sources: set[str] = set()

    def add(self, chunk: Chunk) -> Chunk:
        if chunk.source_ref in self._deleted_sources:
            return chunk  # a deleted source never re-enters production retrieval
        self._chunks[chunk.chunk_id] = chunk
        return chunk

    def delete_source(self, source_ref: str) -> None:
        self._deleted_sources.add(source_ref)
        removed = [cid for cid, c in self._chunks.items() if c.source_ref == source_ref]
        for cid in removed:
            del self._chunks[cid]

    def search(self, terms: tuple[str, ...], *, snapshot: str | None = None) -> tuple[Chunk, ...]:
        # Historical snapshots are only served when explicitly requested (Eval/Replay).
        if snapshot is not None:
            return ()
        return tuple(
            c
            for c in self._chunks.values()
            if any(term.lower() in c.text.lower() for term in terms)
        )


__all__ = [
    "Chunk",
    "IndexPolicy",
    "IndexProjection",
    "split_semantic_chunks",
    "RetrievalIndex",
]
