"""outbox 发布器适配器。

事务性 outbox（CON-013）由发布器排空：每个条目至少投递一次，并依赖代理级别的
去重（NATS ``Nats-Msg-Id`` 或内存中的 event_id 集合），使消费者看到恰好一次
的语义。只有代理接受消息后发布才算成功；随后 outbox 行被标记为已发布。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from ueaf.common.envelope import EventEnvelope
from ueaf.common.identifiers import utcnow
from ueaf.runtime.outbox import OutboxEntry, OutboxStore


class OutboxPublisher(Protocol):
    async def publish(self, entry: OutboxEntry) -> bool: ...

    async def drain(self, outbox: OutboxStore) -> int: ...


def _to_envelope(entry: OutboxEntry) -> EventEnvelope:
    return EventEnvelope(
        event_id=entry.event_id,
        event_name=entry.event_name,
        event_version=entry.event_version,
        occurred_at=entry.created_at,
        recorded_at=entry.published_at or datetime.now(UTC),
        tenant_id=entry.tenant_id,
        aggregate_type=entry.aggregate_type,
        aggregate_id=entry.aggregate_id,
        aggregate_version=entry.aggregate_version,
        sequence=entry.sequence,
        producer="ueaf-outbox-publisher",
        producer_version="0.1.0",
        correlation_id=entry.correlation_id,
        causation_id=entry.causation_id,
        trace_id=entry.trace_id,
        principal_ref=entry.principal_ref,
        release_id=entry.release_id,
        payload_schema_ref=entry.payload_schema_ref,
        payload=entry.payload,
        classification=entry.classification,
        purpose=entry.purpose,
        integrity_ref=entry.integrity_ref,
    )


def _envelope_from_dict(data: dict[str, Any]) -> EventEnvelope:
    """从 JSON wire 字典重建 EventEnvelope（datetime -> ISO 字符串）。"""

    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            try:
                kwargs[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                kwargs[key] = value
        elif isinstance(value, list):
            kwargs[key] = tuple(value)
        else:
            kwargs[key] = value
    return EventEnvelope(**kwargs)


class InMemoryOutboxPublisher:
    """测试/本地发布器：按 event_id 去重，保留已投递的信封。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.events: list[EventEnvelope] = []

    async def publish(self, entry: OutboxEntry) -> bool:
        if entry.event_id in self._seen:
            return False
        self._seen.add(entry.event_id)
        self.events.append(_to_envelope(entry))
        return True

    async def drain(self, outbox: OutboxStore) -> int:
        count = 0
        for entry in await outbox.unpublished():
            if await self.publish(entry):
                await outbox.mark_published(entry.event_id, utcnow())
                count += 1
        return count


class NatsJetStreamOutboxPublisher:
    """将 outbox 条目发布到 NATS JetStream 流。

    ``js`` 是 JetStream 上下文（nats.js）。每条消息都携带 ``Nats-Msg-Id``
    头，其值设为事件 id，使 JetStream 服务端在流的去重窗口内丢弃重复投递。
    ``nats`` 依赖为懒导入，因此缺少它时模块仍可正常导入。
    """

    def __init__(self, js: object, *, subject_prefix: str = "ueaf.events") -> None:
        self._js = js
        self._subject_prefix = subject_prefix

    async def publish(self, entry: OutboxEntry) -> bool:
        _import_nats()  # ensure the dependency is present before publishing
        subject = f"{self._subject_prefix}.{entry.event_name}"
        body = json.dumps(dataclasses.asdict(_to_envelope(entry)), default=str).encode("utf-8")
        ack = await self._js.publish(  # type: ignore[attr-defined]
            subject, body, headers={"Nats-Msg-Id": entry.event_id}
        )
        # 服务端去重：重复的消息 id 会被确认但不存储。
        if getattr(ack, "duplicate", False) or (
            hasattr(ack, "info") and getattr(ack.info, "duplicate", False)
        ):
            return False
        return True

    async def drain(self, outbox: OutboxStore) -> int:
        count = 0
        for entry in await outbox.unpublished():
            if await self.publish(entry):
                await outbox.mark_published(entry.event_id, utcnow())
                count += 1
        return count


def _import_nats() -> Any:
    try:
        import nats
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("nats-py is required for the NATS JetStream outbox publisher") from error
    return nats
