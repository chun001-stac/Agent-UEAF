"""用于恢复/韧性测试（P2-B）的故障注入工具。

``FailureInjector`` 控制场景下一步应在何处失败，``FailingOutboxStore`` 包装
outbox，从而可在事务中途模拟 broker/DB 故障。这些由正式的
``tests/failure_injection`` 套件用于验证原子回滚（CON-013）、fencing
（RUN-003）、timeout-unknown 对账（ACT-003）与至少一次重投递（ACT-013）。
"""

from __future__ import annotations

from typing import Any

from ueaf.runtime.outbox import OutboxEntry, OutboxStore


class FailureInjector:
    """确定性故障开关：使接下来 N 个匹配的操作失败。"""

    def __init__(self) -> None:
        self._fail_remaining: dict[str, int] = {}
        self._triggered: list[str] = []

    def fail_next(self, point: str, *, count: int = 1) -> None:
        if count < 1:
            raise ValueError("count must be >= 1")
        self._fail_remaining[point] = self._fail_remaining.get(point, 0) + count

    def should_fail(self, point: str) -> bool:
        remaining = self._fail_remaining.get(point, 0)
        if remaining <= 0:
            return False
        self._fail_remaining[point] = remaining - 1
        self._triggered.append(point)
        return True

    @property
    def triggered(self) -> list[str]:
        return list(self._triggered)

    def reset(self) -> None:
        self._fail_remaining.clear()
        self._triggered.clear()


class FailingOutboxStore:
    """包装 outbox 存储，当注入器触发时在 ``append`` 上抛出异常。"""

    def __init__(self, inner: OutboxStore, injector: FailureInjector) -> None:
        self._inner = inner
        self._injector = injector

    async def append(self, entry: OutboxEntry) -> None:
        if self._injector.should_fail("outbox.append"):
            raise RuntimeError("injected outbox append failure")
        await self._inner.append(entry)

    async def unpublished(self) -> list[OutboxEntry]:
        return await self._inner.unpublished()

    async def mark_published(self, event_id: str, at: Any = None) -> None:
        await self._inner.mark_published(event_id, at)

    async def dedupe_event_id(self, event_id: str) -> bool:
        return await self._inner.dedupe_event_id(event_id)


__all__ = ["FailureInjector", "FailingOutboxStore"]
