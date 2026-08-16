"""JetStream 消费者序号缺口检测测试（CON-013 发件箱扇出）。

使用模拟 nats-py 的假 JetStream 层，以便在无 broker 的情况下验证持久化消费者
逻辑（重投递去重、前向缺口检测）；真实 NATS 路径由容器端到端测试覆盖
（当 broker 不可达时跳过）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from tests import support
from ueaf.common.identifiers import new_object_id
from ueaf.infrastructure.queue.jetstream import (
    ConsumerStats,
    JetStreamConsumer,
    StreamConfig,
)
from ueaf.runtime.outbox import OutboxEntry


@dataclass
class _FakeSequencePair:
    stream: int
    consumer: int


@dataclass
class _FakeMetadata:
    sequence: _FakeSequencePair


class _FakeMsg:
    def __init__(self, data: bytes, subject: str, stream_seq: int, redelivered: bool) -> None:
        self.data = data
        self.subject = subject
        self.metadata = _FakeMetadata(_FakeSequencePair(stream=stream_seq, consumer=stream_seq))
        self._redelivered = redelivered
        self.acked = False

    async def ack(self) -> None:
        self.acked = True


class _FakeSub:
    def __init__(self, msgs: list[_FakeMsg]) -> None:
        self._queue = list(msgs)
        self.unsubscribed = False

    async def next_msg(self, timeout: float) -> _FakeMsg:
        if not self._queue:
            raise TimeoutError("timeout")
        return self._queue.pop(0)

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class _FakeJetStream:
    def __init__(self, msgs: list[_FakeMsg]) -> None:
        self._msgs = msgs
        self.subscribed = False

    async def stream_info(self, name: str) -> dict[str, Any]:
        return {"config": {"name": name}}

    async def consumer_info(self, stream: str, name: str) -> dict[str, Any] | None:
        return None

    async def subscribe(self, *subjects: str, **kwargs: Any) -> _FakeSub:
        self.subscribed = True
        return _FakeSub(self._msgs)


def _entry(sequence: int) -> OutboxEntry:
    return OutboxEntry(
        outbox_id=new_object_id("outbox"),
        event_id=new_object_id("evt"),
        event_name="ueaf.run.created",
        event_version="1.0.0",
        tenant_id=support.TENANT,
        aggregate_type="RunRecord",
        aggregate_id=f"run:{sequence}",
        aggregate_version=sequence,
        sequence=sequence,
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://run-created/1.0.0",
        payload={"run_id": f"run:{sequence}"},
        created_at=support.now(),
    )


def _wire(entry: OutboxEntry) -> bytes:
    from dataclasses import asdict

    from ueaf.infrastructure.queue.publisher import _to_envelope

    return json.dumps(asdict(_to_envelope(entry)), default=str).encode("utf-8")


@pytest.mark.test_id("CON-013")
async def test_consumer_detects_forward_sequence_gap_and_dedupes() -> None:
    msgs = [
        _FakeMsg(_wire(_entry(1)), "ueaf.events.ueaf.run.created", 1, redelivered=False),
        _FakeMsg(_wire(_entry(2)), "ueaf.events.ueaf.run.created", 2, redelivered=False),
        # 缺少 stream seq 3，构成前向缺口
        _FakeMsg(_wire(_entry(4)), "ueaf.events.ueaf.run.created", 4, redelivered=False),
        # seq 2 被重投递，构成重复
        _FakeMsg(_wire(_entry(2)), "ueaf.events.ueaf.run.created", 2, redelivered=True),
    ]
    js = _FakeJetStream(msgs)
    consumer = JetStreamConsumer(object(), js)

    events = await consumer.fetch("worker-1", max_events=10)
    assert [event.sequence for event, _seq in events] == [1, 2, 4]
    assert consumer.stats.deliveries == 3
    assert consumer.stats.duplicates == 1
    assert len(consumer.stats.gaps) == 1
    gap = consumer.stats.gaps[0]
    assert gap.expected_sequence == 3
    assert gap.observed_sequence == 4


@pytest.mark.test_id("CON-013")
async def test_outbox_wire_roundtrip_through_envelope_codec() -> None:
    entry = _entry(7)
    # 发布者的线上格式必须能解码回等价的事件信封。

    from ueaf.infrastructure.queue.publisher import _envelope_from_dict

    raw = json.loads(_wire(entry).decode("utf-8"))
    envelope = _envelope_from_dict(raw)
    assert envelope.event_id == entry.event_id
    assert envelope.event_name == "ueaf.run.created"
    assert envelope.sequence == 7
    assert envelope.aggregate_id == "run:7"


@pytest.mark.test_id("CON-013")
def test_consumer_stats_defaults() -> None:
    stats = ConsumerStats()
    assert stats.deliveries == 0
    assert stats.duplicates == 0
    assert stats.gaps == []
    assert stats.last_sequence is None
    assert isinstance(stats.gaps, list)


@pytest.mark.test_id("CON-013")
def test_stream_config_defaults() -> None:
    config = StreamConfig()
    assert config.name == "UEAF_EVENTS"
    assert config.subjects == ("ueaf.events.*",)
    assert config.dedup_window_seconds == 120
