"""制品存储：面向大型/高敏感度结果的可控存储。

依据 ACT-016，大型或高敏感度的结果存入受控的制品存储；wire 结果仅保留最小
化的安全摘要/引用。制品不可变，并以 sha256 摘要作为内容寻址。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    key: str
    size: int
    digest: str
    content_type: str | None = None


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> ArtifactRef: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InMemoryArtifactStore:
    """用于测试/本地开发的不可变内存制品存储。"""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str | None]] = {}

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> ArtifactRef:
        if not key:
            raise ValueError("artifact key must not be empty")
        existing = self._objects.get(key)
        if existing is not None and existing[0] != data:
            raise ValueError(f"artifact {key} already exists with different content")
        self._objects[key] = (data, content_type)
        return ArtifactRef(key=key, size=len(data), digest=_digest(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError as error:
            raise KeyError(f"artifact {key} not found") from error

    def exists(self, key: str) -> bool:
        return key in self._objects


class S3ArtifactStore:
    """通过 boto3 实现的 S3 / MinIO 兼容制品存储。

    ``client`` 可注入以用于测试；否则会从 ``endpoint_url``（MinIO）或默认
    AWS 配置懒构建 boto3 客户端。``boto3`` 为懒导入，因此缺少该依赖时模块
    仍可正常导入。
    """

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        client: object | None = None,
        prefix: str = "artifacts",
    ) -> None:
        if not bucket:
            raise ValueError("S3ArtifactStore requires a bucket")
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._endpoint_url = endpoint_url
        self._client = client

    @property
    def _boto(self) -> object:
        if self._client is None:
            boto3 = _import_boto3()
            kwargs = {}
            if self._endpoint_url is not None:
                kwargs["endpoint_url"] = self._endpoint_url
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def put(self, key: str, data: bytes, *, content_type: str | None = None) -> ArtifactRef:
        object_key = f"{self._prefix}/{key}"
        # 不可变性（ACT-016）：已存在的对象绝不能静默地
        # 被不同内容替换。
        if self.exists(key):
            existing = self.get(key)
            if existing != data:
                raise ValueError(f"artifact {key} already exists with different content")
        extra = {"ContentType": content_type} if content_type else None
        self._boto.put_object(  # type: ignore[attr-defined]
            Bucket=self._bucket,
            Key=object_key,
            Body=data,
            **(extra or {}),
        )
        return ArtifactRef(key=key, size=len(data), digest=_digest(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        response = self._boto.get_object(  # type: ignore[attr-defined]
            Bucket=self._bucket, Key=f"{self._prefix}/{key}"
        )
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def exists(self, key: str) -> bool:
        try:
            self._boto.head_object(  # type: ignore[attr-defined]
                Bucket=self._bucket, Key=f"{self._prefix}/{key}"
            )
            return True
        except Exception:
            return False


def _import_boto3() -> Any:
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("boto3 is required for the S3/MinIO artifact store") from error
    return boto3
