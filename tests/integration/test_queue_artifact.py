"""Queue/artifact wiring tests (outbox publisher + object storage)."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest

from tests import support
from ueaf.common.identifiers import new_object_id
from ueaf.infrastructure.artifact.store import (
    InMemoryArtifactStore,
    S3ArtifactStore,
)
from ueaf.infrastructure.queue.publisher import (
    InMemoryOutboxPublisher,
    NatsJetStreamOutboxPublisher,
)
from ueaf.runtime.outbox import InMemoryOutboxStore, OutboxEntry


def _entry(event_name: str = "ueaf.run.created") -> OutboxEntry:
    return OutboxEntry(
        outbox_id=new_object_id("outbox"),
        event_id=new_object_id("evt"),
        event_name=event_name,
        event_version="1.0.0",
        tenant_id=support.TENANT,
        aggregate_type="RunRecord",
        aggregate_id="run:1",
        aggregate_version=1,
        sequence=1,
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://run-created/1.0.0",
        payload={"run_id": "run:1", "task_id": "task:1", "release_id": "release:1",
                 "runtime_adapter_ref": "adapter:langgraph"},
        created_at=datetime.now(UTC),
    )


@pytest.mark.test_id("CON-013")
def test_in_memory_publisher_drains_and_dedupes_outbox() -> None:
    outbox = InMemoryOutboxStore()
    entry = _entry()
    outbox.append(entry)

    publisher = InMemoryOutboxPublisher()
    assert publisher.drain(outbox) == 1
    assert outbox.dedupe_event_id(entry.event_id)

    # Nothing left to publish; redelivery is deduped by event_id.
    assert publisher.drain(outbox) == 0
    assert len(publisher.events) == 1
    assert publisher.events[0].event_name == "ueaf.run.created"


class _FakeAck:
    def __init__(self, *, duplicate: bool) -> None:
        self.duplicate = duplicate
        self.info = type("Info", (), {"duplicate": duplicate})()


class _FakeJetStream:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self._seen: set[str] = set()

    async def publish(
        self, subject: str, payload: bytes, headers: dict[str, str] | None = None
    ) -> _FakeAck:
        headers = headers or {}
        msg_id = headers.get("Nats-Msg-Id", "")
        self.calls.append((subject, payload, dict(headers)))
        if msg_id in self._seen:
            return _FakeAck(duplicate=True)  # JetStream dedup drop
        self._seen.add(msg_id)
        return _FakeAck(duplicate=False)


@pytest.mark.test_id("CON-013")
def test_nats_publisher_sends_msg_id_and_marks_published() -> None:
    fake = _FakeJetStream()
    publisher = NatsJetStreamOutboxPublisher(fake, subject_prefix="ueaf.events")
    outbox = InMemoryOutboxStore()
    entry = _entry()
    outbox.append(entry)

    asyncio.run(publisher.drain(outbox))
    assert outbox.dedupe_event_id(entry.event_id)
    assert len(fake.calls) == 1
    subject, _payload, headers = fake.calls[0]
    assert subject == f"ueaf.events.{entry.event_name}"
    assert headers.get("Nats-Msg-Id") == entry.event_id


@pytest.mark.test_id("ACT-016")
def test_artifact_store_put_get_digest_and_immutability() -> None:
    store = InMemoryArtifactStore()
    payload = b'{"summary": "large result artifact"}'
    ref = store.put("result:1", payload, content_type="application/json")

    assert store.get("result:1") == payload
    assert ref.digest == hashlib.sha256(payload).hexdigest()
    assert ref.size == len(payload)

    # Artifacts are immutable: same key with different content is rejected.
    with pytest.raises(ValueError, match="already exists"):
        store.put("result:1", b"different-content")


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: object) -> None:
        self.objects[str(kwargs["Key"])] = bytes(kwargs["Body"])  # type: ignore[arg-type]

    def get_object(self, **kwargs: object) -> dict[str, object]:
        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.objects[str(kwargs["Key"])])}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        if str(kwargs["Key"]) not in self.objects:
            raise KeyError("not found")
        return {}


@pytest.mark.test_id("ACT-016")
def test_s3_artifact_store_wiring_with_fake_client() -> None:
    client = _FakeS3Client()
    store = S3ArtifactStore("ueaf-artifacts", client=client, prefix="artifacts")

    ref = store.put("result:1", b"data", content_type="application/octet-stream")
    assert ref.digest == hashlib.sha256(b"data").hexdigest()
    assert store.get("result:1") == b"data"
    assert store.exists("result:1")
    assert not store.exists("missing")
    assert client.objects["artifacts/result:1"] == b"data"
