"""规范对象的确定性标识符 / 引用辅助函数。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime


def utcnow() -> datetime:
    """整个实现统一使用的带时区 RFC 3339 UTC 时间戳。"""
    return datetime.now(UTC)


def new_object_id(prefix: str) -> str:
    """生成抗碰撞的规范对象 id。"""
    if not prefix:
        raise ValueError("prefix must not be empty")
    return f"{prefix}:{secrets.token_hex(12)}"


def sha256_hex(text: str) -> str:
    """用于完整性/证据引用的稳定 sha256 十六进制摘要。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_ref(parts: tuple[str, ...]) -> str:
    """稳定、以冒号连接生成的引用；绝不信任调用方提供的顺序。"""
    return ":".join(parts)
