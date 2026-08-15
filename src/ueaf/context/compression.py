"""History compression lineage (CTX-005).

Compression is traceable: every compressed summary records its input refs,
output ref, rule/model version and loss/omissions. Beyond a reference depth, a
compressed summary must be rebuilt from authoritative history rather than
compressed further ("summary of a summary" is never unbounded).
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
    """Tracks compression depth and rebuilds beyond the reference depth (CTX-005)."""

    max_depth: int = 3
    records: list[CompressionRecord] = field(default_factory=list)

    def record(self, record: CompressionRecord) -> CompressionRecord:
        self.records.append(record)
        return record

    @property
    def depth(self) -> int:
        return len(self.records)

    def needs_rebuild(self) -> bool:
        """Beyond the reference depth, rebuild instead of compressing further."""
        return self.depth >= self.max_depth

    def rebuild_from(self, authoritative_refs: tuple[str, ...]) -> CompressionRecord:
        """Start a fresh lineage from authoritative history (resets depth)."""
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
