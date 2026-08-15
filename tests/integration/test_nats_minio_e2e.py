"""NATS JetStream + MinIO end-to-end integration tests.

Exercises the real broker/object-store path: outbox -> NATS JetStream stream ->
durable consumer (sequence-gap detection), and artifact put/get against MinIO.
Skipped when the containers are unreachable (CI without the docker services) or
the optional dependencies (``nats``, ``boto3``) are not installed.
"""

from __future__ import annotations

import hashlib
import os
import socket

import pytest

from tests import support
from ueaf.common.identifiers import new_object_id
from ueaf.infrastructure.artifact.store import S3ArtifactStore
from ueaf.infrastructure.queue.jetstream import JetStreamConsumer, StreamConfig
from ueaf.infrastructure.queue.publisher import NatsJetStreamOutboxPublisher
from ueaf.runtime.outbox import InMemoryOutboxStore, OutboxEntry

NATS_URL = os.environ.get("UEAF_NATS_URL", "nats://127.0.0.1:4222")
MINIO_ENDPOINT = os.environ.get("UEAF_MINIO_ENDPOINT", "http://127.0.0.1:9000")
MINIO_BUCKET = os.environ.get("UEAF_MINIO_BUCKET", "ueaf-artifacts")
MINIO_ACCESS = os.environ.get("UEAF_MINIO_ACCESS_KEY", "ueaf")
MINIO_SECRET = os.environ.get("UEAF_MINIO_SECRET_KEY", "ueaf-local-dev-change-me")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _deps_available() -> bool:
    try:
        import boto3  # noqa: F401
        import nats  # noqa: F401
    except ImportError:
        return False
    return True


requires_live = pytest.mark.skipif(
    not _deps_available() or not _port_open("127.0.0.1", 4222),
    reason="requires nats/boto3 and a reachable NATS/MinIO (docker compose up -d nats minio)",
)


def _entry(event_name: str, sequence: int, aggregate_id: str) -> OutboxEntry:
    return OutboxEntry(
        outbox_id=new_object_id("outbox"),
        event_id=new_object_id("evt"),
        event_name=event_name,
        event_version="1.0.0",
        tenant_id=support.TENANT,
        aggregate_type="RunRecord",
        aggregate_id=aggregate_id,
        aggregate_version=sequence,
        sequence=sequence,
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://run-created/1.0.0",
        payload={"run_id": aggregate_id, "sequence": sequence},
        created_at=support.now(),
    )


@requires_live
@pytest.mark.test_id("CON-013")
async def test_outbox_publishes_to_live_jetstream_and_consumes_exactly_once() -> None:
    import nats

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    stream = StreamConfig(
        name=f"UEAF_E2E_{os.getpid()}",
        subjects=(f"ueaf.e2e.{os.getpid()}.>",),
        max_age_seconds=3600,
    )
    consumer = JetStreamConsumer(nc, js, stream=stream)
    info = await consumer.bootstrap_stream()
    assert info.config.name == stream.name

    try:
        publisher = NatsJetStreamOutboxPublisher(js, subject_prefix=f"ueaf.e2e.{os.getpid()}")
        outbox = InMemoryOutboxStore()
        entry_a = _entry("ueaf.run.created", 1, "run:e2e-1")
        entry_b = _entry("ueaf.run.phase_changed", 2, "run:e2e-1")
        await outbox.append(entry_a)
        await outbox.append(entry_b)

        # Drain the outbox to the broker; both rows are marked published.
        assert await publisher.drain(outbox) == 2
        assert await outbox.dedupe_event_id(entry_a.event_id)
        assert await outbox.dedupe_event_id(entry_b.event_id)
        assert await publisher.drain(outbox) == 0  # nothing left

        # A durable consumer receives both events with no forward gaps.
        delivered = await consumer.fetch("worker-e2e", max_events=2)
        names = sorted(event.event_name for event, _seq in delivered)
        assert names == ["ueaf.run.created", "ueaf.run.phase_changed"]
        assert consumer.stats.deliveries == 2
        assert consumer.stats.gaps == []
        assert consumer.stats.last_sequence == 2
    finally:
        await nc.close()


@requires_live
@pytest.mark.test_id("ACT-016")
async def test_artifact_roundtrip_through_live_minio() -> None:
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
        region_name="us-east-1",
    )
    try:
        client.create_bucket(Bucket=MINIO_BUCKET)
    except ClientError as error:
        # BucketAlreadyOwnedByYou / already exists is fine.
        if "BucketAlready" not in str(error):
            raise

    store = S3ArtifactStore(MINIO_BUCKET, endpoint_url=MINIO_ENDPOINT, client=client)
    key = f"run:e2e/{new_object_id('artifact')}.json"
    payload = b'{"summary": "e2e large result artifact"}'
    ref = store.put(key, payload, content_type="application/json")
    assert ref.digest == hashlib.sha256(payload).hexdigest()
    assert store.exists(key)

    fetched = store.get(key)
    assert fetched == payload

    # Immutability: the same key with different content must not silently replace.
    with pytest.raises(ValueError):
        store.put(key, b"different-content")
    # Idempotent re-put of identical content is allowed.
    store.put(key, payload, content_type="application/json")
