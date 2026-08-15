"""LangGraph Runtime Adapter (Adapter #1).

A thin, deterministic CI-safe wrapper over the core ``RuntimeAdapter`` SPI that
drives the controlled smoke chain strictly through the whitelisted ports
(ADP-001/002). In production this would map to a LangGraph compiled graph; in
the reference implementation the graph step is the deterministic chain itself.
"""

from __future__ import annotations

from ueaf.adapters.runtimes.base import DeterministicRuntimeAdapter


class LangGraphAdapter(DeterministicRuntimeAdapter):
    """LangGraph adapter: same controlled chain, distinct adapter identity."""

    def __init__(self) -> None:
        super().__init__(
            adapter_ref="adapter:langgraph",
            supported_contract_versions=("1.0.0",),
        )
