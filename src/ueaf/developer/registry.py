"""Adapter registry for external agent runtimes (functional module 10).

External frameworks (LangGraph, OpenAI Agents SDK, ...) plug in via a
RuntimeAdapter; the developer registry tracks which adapters are available and
which contract versions they support.
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
    """Minimal structural type for a pluggable external runtime."""

    def DescribeRuntime(self) -> RuntimeCapabilities: ...


@dataclass(slots=True)
class AdapterRegistry:
    """Maps adapter refs to runtime adapter instances + capabilities."""

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
