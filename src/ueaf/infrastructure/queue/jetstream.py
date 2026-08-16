"""NATS JetStream 引导 + 带序列号缺口检测的消费者。

事务性 outbox（CON-013）由发布器排空；订阅方需要一个持久化 JetStream 消费者，
使重启后的 worker 能精确地从上次位置恢复。``JetStreamConsumer`` 跟踪每个流的
序列号，当某条消息的流序列号跳过了上一条已投递的序列号时报告缺口
（``SequenceGap``）—— 这意味着有投递被遗漏，消费者在盲目处理下一条事件前
需要进行对账。

``nats`` 依赖为懒导入，因此缺少它时模块仍可正常导入。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ueaf.common.envelope import EventEnvelope


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """用于幂等引导的 JetStream 流配置。"""

    name: str = "UEAF_EVENTS"
    subjects: tuple[str, ...] = ("ueaf.events.*",)
    max_age_seconds: int = 86400  # 24 小时
    max_msgs: int = 100_000
    dedup_window_seconds: int = 120  # 服务端去重窗口（Nats-Msg-Id）


@dataclass(frozen=True, slots=True)
class SequenceGap:
    """检测到的投递缺口：某个流序列号被跳过。"""

    subject: str
    expected_sequence: int
    observed_sequence: int
    event_id: str | None


@dataclass(slots=True)
class ConsumerStats:
    deliveries: int = 0
    duplicates: int = 0
    gaps: list[SequenceGap] = field(default_factory=list)
    last_sequence: int | None = None


class JetStreamConsumer:
    """JetStream 流上的持久化消费者，带序列号缺口检测。"""

    def __init__(self, nc: object, js: object, *, stream: StreamConfig | None = None) -> None:
        self._nc = nc
        self._js = js
        self._stream = stream or StreamConfig()
        self.stats = ConsumerStats()

    async def bootstrap_stream(self) -> Any:
        """若流不存在则创建；返回流信息对象。"""
        try:
            return await self._js.stream_info(  # type: ignore[attr-defined]
                self._stream.name
            )
        except Exception:
            await self._js.add_stream(  # type: ignore[attr-defined]
                name=self._stream.name,
                subjects=list(self._stream.subjects),
                max_age=self._stream.max_age_seconds,
                max_msgs=self._stream.max_msgs,
                duplicate_window=self._stream.dedup_window_seconds,
            )
            return await self._js.stream_info(  # type: ignore[attr-defined]
                self._stream.name
            )

    async def consumer_info(self, consumer_name: str) -> Any:
        """返回持久化消费者信息，若不存在则返回 ``None``。"""
        try:
            return await self._js.consumer_info(  # type: ignore[attr-defined]
                self._stream.name, consumer_name
            )
        except Exception:
            return None

    async def subscribe(
        self, consumer_name: str, *, durable: bool = True
    ) -> AsyncIterator[tuple[EventEnvelope, int]]:
        """订阅；每条已投递消息产出 ``(event, stream_sequence)``。

        重复消息（JetStream ``redelivered``）会被计数并跳过；向前的序列号跳变
        记录为 ``SequenceGap``，但消息仍会产出，以便调用方决定对账还是跳过。
        """
        kwargs = {}
        if durable:
            kwargs["durable"] = consumer_name
        sub = await self._js.subscribe(  # type: ignore[attr-defined]
            *self._stream.subjects, stream=self._stream.name, **kwargs
        )
        try:
            while True:
                msg = await sub.next_msg(timeout=0.5)
                meta = getattr(msg, "metadata", None)
                stream_seq = getattr(meta, "sequence", None)
                seq = int(stream_seq.stream) if stream_seq is not None else 0
                if self.stats.last_sequence is not None and seq <= self.stats.last_sequence:
                    self.stats.duplicates += 1
                    await msg.ack()
                    continue
                if self.stats.last_sequence is not None and seq > self.stats.last_sequence + 1:
                    self.stats.gaps.append(
                        SequenceGap(
                            subject=msg.subject,
                            expected_sequence=self.stats.last_sequence + 1,
                            observed_sequence=seq,
                            event_id=None,
                        )
                    )
                self.stats.last_sequence = seq
                self.stats.deliveries += 1
                await msg.ack()
                yield _decode_event(msg.data), seq
        except TimeoutError:
            return
        finally:
            try:
                await sub.unsubscribe()
            except Exception:
                pass

    async def fetch(
        self, consumer_name: str, *, max_events: int = 16, timeout: float = 1.0
    ) -> list[tuple[EventEnvelope, int]]:
        """最多收集 ``max_events`` 条事件，然后取消订阅。"""
        events: list[tuple[EventEnvelope, int]] = []
        async for event, seq in self.subscribe(consumer_name, durable=True):
            events.append((event, seq))
            if len(events) >= max_events:
                break
        return events


def _decode_event(data: bytes) -> EventEnvelope:
    import json

    from ueaf.infrastructure.queue.publisher import _envelope_from_dict

    payload = json.loads(data.decode("utf-8"))
    return _envelope_from_dict(payload)


__all__ = [
    "StreamConfig",
    "SequenceGap",
    "ConsumerStats",
    "JetStreamConsumer",
]
