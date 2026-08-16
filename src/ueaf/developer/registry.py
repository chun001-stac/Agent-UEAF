"""外部 agent 运行时适配器注册表（功能模块 10）。

外部框架（LangGraph、OpenAI Agents SDK 等）通过 RuntimeAdapter 接入；开发者注册表
跟踪哪些适配器可用以及它们支持的合约版本。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ueaf.adapters.runtimes.base import (
    DeterministicRuntimeAdapter,
)
from ueaf.adapters.runtimes.langgraph_adapter import LangGraphAdapter
from ueaf.adapters.runtimes.openai_agents_adapter import OpenAIAgentsReadOnlyAdapter
from ueaf.ports import RuntimeCapabilities


@dataclass(frozen=True, slots=True)
class AdapterEntry:
    ref: str
    kind: str
    supported_contract_versions: tuple[str, ...]
    read_only: bool


class RuntimeAdapter(Protocol):
    """可插拔外部运行时的最小结构类型。"""

    def DescribeRuntime(self) -> RuntimeCapabilities: ...


@dataclass(slots=True)
class AdapterRegistry:
    """将适配器引用映射到运行时适配器实例 + 能力。"""

    _factories: dict[str, Callable[[], RuntimeAdapter]] = field(default_factory=dict)

    def register(self, ref: str, factory: Callable[[], RuntimeAdapter]) -> None:
        self._factories[ref] = factory

    def build(self, ref: str) -> RuntimeAdapter:
        factory = self._factories.get(ref)
        if factory is None:
            raise KeyError(f"no runtime adapter registered for {ref!r}")
        return factory()


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register("adapter:deterministic", DeterministicRuntimeAdapter)
    registry.register("adapter:langgraph", LangGraphAdapter)
    registry.register("adapter:openai-agents", OpenAIAgentsReadOnlyAdapter)
    return registry
