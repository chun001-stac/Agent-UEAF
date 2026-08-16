"""RAG 嵌入测试：确定性哈希 + 懒加载本地 BGE 嵌入。

RAG-009 确定性融合稳定性：DeterministicHashEmbedding 在多次调用和多个实例间
可复现，因此 RRF 融合保持稳定。
RAG-010 降级词法兜底：BgeLocalEmbedding 为懒加载（导入/构造时不下载模型），
当 sentence-transformers 缺失时会抛出明确错误，从而驱动降级词法路径。
"""

from __future__ import annotations

import pytest

from ueaf.rag.embedding import (
    BgeLocalEmbedding,
    DeterministicHashEmbedding,
    EmbeddingProvider,
)

_TEXT = "orders reconciliation across desks"


@pytest.mark.test_id("RAG-009")
def test_deterministic_hash_embedding_satisfies_provider_contract() -> None:
    # 静态检查具体提供方是否满足 EmbeddingProvider SPI。
    _check_provider(DeterministicHashEmbedding())
    # BgeLocalEmbedding 是懒加载的（构造时不加载模型），因此这里只检查其可查询的
    # 契约；embed 路径由下方 monkeypatch 的懒加载 / 依赖缺失测试覆盖。
    bge = BgeLocalEmbedding()
    assert bge.name
    assert bge.dimension >= 1
    assert bge.model_name


def _check_provider(provider: EmbeddingProvider) -> None:
    assert provider.name
    assert provider.dimension >= 1
    vectors = provider.embed((_TEXT,))
    assert len(vectors) == 1
    assert len(vectors[0]) == provider.dimension


@pytest.mark.test_id("RAG-009")
def test_deterministic_hash_embedding_is_reproducible() -> None:
    embedder = DeterministicHashEmbedding(dimension=16)
    first = embedder.embed((_TEXT,))
    second = embedder.embed((_TEXT,))
    assert first == second
    # 在独立实例之间同样是确定性的。
    assert first == DeterministicHashEmbedding(dimension=16).embed((_TEXT,))
    # 语义不同的文本会产生不同的向量。
    assert first != embedder.embed(("revenue forecast",))


@pytest.mark.test_id("RAG-009")
def test_deterministic_hash_embedding_dimension_and_norm() -> None:
    embedder = DeterministicHashEmbedding(dimension=64)
    assert embedder.dimension == 64
    vector = embedder.embed((_TEXT,))[0]
    assert len(vector) == 64
    # L2 归一化的单位向量，因此余弦相似度定义明确。
    norm = sum(value * value for value in vector) ** 0.5
    assert norm == pytest.approx(1.0)


@pytest.mark.test_id("RAG-010")
def test_bge_local_embedding_is_lazy_and_loads_on_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ueaf.rag.embedding as embedding_mod

    constructed: list[tuple[str, ...]] = []

    class _FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            constructed.append((model_name,))

        def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
            del normalize_embeddings
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        embedding_mod, "_import_sentence_transformers", lambda: _FakeSentenceTransformer
    )
    embedder = BgeLocalEmbedding(model_name="fake/bge-small")
    # 构造时必须不下载/加载模型（懒加载）。
    assert constructed == []
    # 加载前即可查询 dimension。
    assert embedder.dimension == 512
    assert embedder.name == "bge-local:fake/bge-small"
    vectors = embedder.embed(("hello", "world"))
    # 模型在首次 embed 调用时恰好加载一次。
    assert constructed == [("fake/bge-small",)]
    assert vectors == ((1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    assert embedder.embed(("again",)) == ((1.0, 0.0, 0.0),)
    assert constructed == [("fake/bge-small",)]


@pytest.mark.test_id("RAG-010")
def test_bge_local_embedding_reports_missing_dependency_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ueaf.rag.embedding as embedding_mod

    def _missing() -> object:
        raise RuntimeError(
            "BgeLocalEmbedding 需要安装 sentence-transformers；请通过 "
            "`pip install 'sentence-transformers>=3,<5'` 安装"
        )

    monkeypatch.setattr(embedding_mod, "_import_sentence_transformers", _missing)
    embedder = BgeLocalEmbedding()
    # 构造仍为懒加载；只有首次 embed 调用会以明确错误失败。
    with pytest.raises(RuntimeError, match="sentence-transformers"):
        embedder.embed(("hello",))
