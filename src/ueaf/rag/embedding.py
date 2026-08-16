"""RAG 嵌入：本地 sentence-transformers + 确定性哈希兜底。

嵌入向量为 RAG-009 混合检索的向量通道提供输入。生产环境使用的提供方是本地
``BAAI/bge-small-zh-v1.5`` 模型（无需外部 API 密钥）；模型采用懒加载，因此导入
本模块不会下载模型，且在加载前即可查询 ``dimension``。为满足 CI/单元测试以及
RAG-009 确定性融合的稳定性要求，提供了一种确定性、零依赖的哈希嵌入。当嵌入
不可用时，混合检索器会降级为仅词法检索（RAG-010）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol

from ueaf.common.identifiers import sha256_hex

DEFAULT_BGE_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_BGE_DIMENSION = 512


class EmbeddingProvider(Protocol):
    """混合检索器与索引流水线使用的最小嵌入 SPI。"""

    @property
    def name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


class DeterministicHashEmbedding:
    """用于 CI/单元测试的确定性、零依赖嵌入（RAG-009/010）。

    每个维度都是基于 sha256 的稳定取值，范围在 [-1, 1] 内，且向量经过 L2 归一化，
    因此余弦相似度定义明确，并且在多次调用、多个进程和多次运行之间可复现——
    无需任何外部模型即可满足 RAG-009 的稳定性要求。
    """

    def __init__(self, *, dimension: int = 64) -> None:
        if dimension < 1:
            raise ValueError("dimension must be >= 1")
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "deterministic-hash@1.0"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self._dimension
        for index in range(self._dimension):
            digest = sha256_hex(f"{text}::{index}")
            scaled = int(digest[:8], 16) / 0xFFFFFFFF
            values[index] = scaled * 2.0 - 1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return tuple(value / norm for value in values)


class BgeLocalEmbedding:
    """本地 sentence-transformers 嵌入（无需外部 API 密钥）。

    模型在首次调用 ``embed`` 时懒加载，因此导入或构造此类不会下载模型。
    ``sentence-transformers`` 同样为懒导入，缺失时会抛出明确的 ``RuntimeError``
    （混合检索器会据此走 RAG-010 降级词法路径）。
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_BGE_MODEL,
        dimension: int = DEFAULT_BGE_DIMENSION,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._model: Any | None = None

    @property
    def name(self) -> str:
        return f"bge-local:{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        model = self._model_or_load()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return tuple(tuple(float(value) for value in row) for row in vectors)

    def _model_or_load(self) -> Any:
        if self._model is None:
            self._model = _import_sentence_transformers()(self._model_name)
        return self._model


def _import_sentence_transformers() -> Any:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError(
            "BgeLocalEmbedding 需要安装 sentence-transformers；请通过 "
            "`pip install 'sentence-transformers>=3,<5'` 安装"
        ) from error
    return SentenceTransformer


__all__ = [
    "EmbeddingProvider",
    "DeterministicHashEmbedding",
    "BgeLocalEmbedding",
    "DEFAULT_BGE_MODEL",
    "DEFAULT_BGE_DIMENSION",
]
