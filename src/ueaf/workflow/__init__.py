"""工作流 / 多 agent 交接编排（功能模块 06）。

``WorkflowCoordinator`` 通过核心 HandoffPort 驱动 HandoffEnvelope 交换；子目标被
预算切片且归属明确。它自身绝不创建运行权威事件（运行仍归 RunCoordinator 所有）。
"""
