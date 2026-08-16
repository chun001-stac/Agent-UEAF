"""密钥提供者抽象（实现规范 05 §16，SEC-013）。

密钥绝不进入补丁、提示词、日志、事件或测试夹具。``SecretProvider`` 仅在
执行器内部将不透明引用解析为值。
"""

from __future__ import annotations

import os
from typing import Protocol


class SecretProvider(Protocol):
    def resolve(self, secret_ref: str) -> str: ...

    def exists(self, secret_ref: str) -> bool: ...


class EnvSecretProvider:
    """基于环境变量的密钥提供者（仅本地开发）。"""

    def __init__(self, prefix: str = "UEAF_SECRET_") -> None:
        self._prefix = prefix

    @staticmethod
    def _key(secret_ref: str) -> str:
        if not secret_ref or ":" not in secret_ref:
            raise ValueError("secret_ref must be opaque, e.g. 'env:API_KEY'")
        return secret_ref.split(":", 1)[1]

    def resolve(self, secret_ref: str) -> str:
        value = os.environ.get(f"{self._prefix}{self._key(secret_ref)}")
        if value is None:
            raise KeyError(f"secret {secret_ref} not available")
        return value

    def exists(self, secret_ref: str) -> bool:
        return os.environ.get(f"{self._prefix}{self._key(secret_ref)}") is not None


class InMemorySecretProvider:
    """测试用密钥后端；绝不用于真实凭据。"""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})

    def resolve(self, secret_ref: str) -> str:
        key = secret_ref.split(":", 1)[1] if ":" in secret_ref else secret_ref
        try:
            return self._secrets[key]
        except KeyError as error:
            raise KeyError(f"secret {secret_ref} not available") from error

    def exists(self, secret_ref: str) -> bool:
        key = secret_ref.split(":", 1)[1] if ":" in secret_ref else secret_ref
        return key in self._secrets
