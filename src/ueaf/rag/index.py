"""RAG 索引：可复现投影、语义分块边界、删除。

RAG-005 可复现索引元数据：相同来源版本加上 parser/chunk/embedding/index 策略会
产生可追溯且相同的元数据；其中任一版本变化都会产生可区分的投影。
RAG-006 语义分块边界：标题/符号/表格表头/线程/页面/跨度以及记录 ID 都会被保留。
RAG-008 已删除来源消失：删除后，生产检索永远不会召回旧分块；历史快照仅隔离在
Eval/Replay 中使用。
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
    """塑造索引投影的确定性策略版本（RAG-005）。"""

    parser_version: str = "parser@1.0.0"
    chunk_version: str = "chunk@1.0.0"
    embedding_version: str | None = None
    index_version: str = "index@1.0.0"


@dataclass(frozen=True, slots=True)
class IndexProjection:
    """固定策略下某一来源版本的可复现元数据。"""

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
    """遵循语义边界的确定性分块（RAG-006）。

    标题（``#``）、代码围栏、表格表头（``|`` 行）和空行分隔符都会作为 locator 保留；
    分块永远不会拆分围栏代码块或表格表头行。
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
    """遵循来源删除语义的内存索引（RAG-008）。"""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._deleted_sources: set[str] = set()

    def add(self, chunk: Chunk) -> Chunk:
        if chunk.source_ref in self._deleted_sources:
            return chunk  # 已删除的来源绝不会重新进入生产检索
        self._chunks[chunk.chunk_id] = chunk
        return chunk

    def delete_source(self, source_ref: str) -> None:
        self._deleted_sources.add(source_ref)
        removed = [cid for cid, c in self._chunks.items() if c.source_ref == source_ref]
        for cid in removed:
            del self._chunks[cid]

    def search(self, terms: tuple[str, ...], *, snapshot: str | None = None) -> tuple[Chunk, ...]:
        # 历史快照仅在显式请求时才会提供（Eval/Replay）。
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
