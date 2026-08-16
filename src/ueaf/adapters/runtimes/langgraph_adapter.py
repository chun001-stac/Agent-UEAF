"""LangGraph 运行时适配器（适配器 #1）。

核心 ``RuntimeAdapter`` SPI 之上的轻量、确定性且 CI 安全的包装器，严格通过
白名单端口驱动受控冒烟链（ADP-001/002）。在生产环境中它会映射到 LangGraph
编译图；在参考实现中，图步骤本身就是这个确定性链。
"""

from __future__ import annotations

from ueaf.adapters.runtimes.base import DeterministicRuntimeAdapter


class LangGraphAdapter(DeterministicRuntimeAdapter):
    """LangGraph 适配器：同样的受控链，不同的适配器身份。"""

    def __init__(self) -> None:
        super().__init__(
            adapter_ref="adapter:langgraph",
            supported_contract_versions=("1.0.0",),
        )
