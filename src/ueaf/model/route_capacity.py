"""路由容量门控：冻结的 ContextManifest 绝不被变异（PRM-006）。

模块 03（Model/Prompt）选择路由；如果该路由无法容纳模块 04 已生成的冻结
ContextManifest，请求将以结构化的预算问题失败，而不是截断或重写清单。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.ports import ContextManifest


@dataclass(frozen=True, slots=True)
class RouteCapacityDecision:
    accepted: bool
    route_capacity_tokens: int
    required_tokens: int
    reason_codes: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return not self.accepted


def estimate_manifest_tokens(manifest: ContextManifest) -> int:
    """冻结清单的确定性 token 估算（绝不变异）。"""
    return 64 + len(manifest.evidence_pack_refs) * 24 + len(manifest.integrity_ref or "")


class RouteCapacityGate:
    """检查路由能否容纳冻结的清单；清单只读（PRM-006）。"""

    def __init__(self, *, reserve_tokens: int = 128) -> None:
        self._reserve_tokens = reserve_tokens

    def evaluate(
        self, manifest: ContextManifest, *, route_capacity_tokens: int
    ) -> RouteCapacityDecision:
        required = estimate_manifest_tokens(manifest) + self._reserve_tokens
        if required > route_capacity_tokens:
            return RouteCapacityDecision(
                False,
                route_capacity_tokens,
                required,
                ("route_cannot_fit_frozen_manifest",),
            )
        return RouteCapacityDecision(True, route_capacity_tokens, required, ("fit",))


__all__ = ["RouteCapacityGate", "RouteCapacityDecision", "estimate_manifest_tokens"]
