"""历史压缩谱系（CTX-005）。

压缩是可追溯的：每个压缩摘要都记录其输入引用、输出引用、规则/模型版本以及损失/省略。
超过参考深度后，压缩摘要必须从权威历史重建，而不是继续压缩（“摘要的摘要”绝非无界）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class CompressionRecord:
    summary_ref: str
    input_refs: tuple[str, ...]
    output_ref: str
    rule_version: str
    loss: int
    omitted_refs: tuple[str, ...] = ()

    @property
    def lineage_digest(self) -> str:
        return sha256_hex(
            "|".join(
                [
                    self.summary_ref,
                    *self.input_refs,
                    self.output_ref,
                    self.rule_version,
                    str(self.loss),
                ]
            )
        )


@dataclass(slots=True)
class CompressionLineage:
    """跟踪压缩深度，并在超过参考深度时重建（CTX-005）。"""

    max_depth: int = 3
    records: list[CompressionRecord] = field(default_factory=list)

    def record(self, record: CompressionRecord) -> CompressionRecord:
        self.records.append(record)
        return record

    @property
    def depth(self) -> int:
        return len(self.records)

    def needs_rebuild(self) -> bool:
        """超过参考深度时，重建而不是继续压缩。"""
        return self.depth >= self.max_depth

    def rebuild_from(self, authoritative_refs: tuple[str, ...]) -> CompressionRecord:
        """从权威历史开始新的谱系（重置深度）。"""
        self.records.clear()
        record = CompressionRecord(
            summary_ref="summary:rebuilt",
            input_refs=authoritative_refs,
            output_ref="summary:rebuilt",
            rule_version="1.0.0",
            loss=0,
        )
        self.records.append(record)
        return record


__all__ = ["CompressionRecord", "CompressionLineage"]
