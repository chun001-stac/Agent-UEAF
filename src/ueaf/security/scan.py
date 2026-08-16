"""凭据扫描：内容域中不允许出现凭据材料（SEC-003）。

提示词、工具参数、普通日志/轨迹/事件载荷以及进化工作集（Working Set）绝不允许携带
凭据材料。``CredentialScanner`` 使用保守的模式进行匹配，当某个扫描域命中时抛出
``CredentialScanError``。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# 保守的凭据标记（避免对普通文本产生大量误报）。
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:password|passwd)\s*[=:]\s*[^\s,;]{4,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?key)\s*[=:]\s*[^\s,;]{8,}"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # 类似 JWT 的形式
)


class CredentialScanError(RuntimeError):
    """在内容域中发现凭据材料时抛出（SEC-003）。"""


class CredentialScanner:
    """扫描指定的内容域以查找凭据材料。"""

    def __init__(self, patterns: tuple[re.Pattern[str], ...] | None = None) -> None:
        self._patterns = patterns or _CREDENTIAL_PATTERNS

    def find_in(self, text: str) -> list[str]:
        """返回 ``text`` 中命中的脱敏模式名（绝不返回值本身）。"""
        found: list[str] = []
        for pattern in self._patterns:
            match = pattern.search(text)
            if match is not None:
                found.append(f"{pattern.pattern[:24]}…")
        return found

    def scan(
        self,
        *,
        prompt: str | None = None,
        tool_args: Mapping[str, Any] | None = None,
        log: str | None = None,
        trace: Mapping[str, Any] | None = None,
        event_payload: Mapping[str, Any] | None = None,
        working_set: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """扫描所有提供的域；返回有命中的域名列表。"""
        hits: list[str] = []
        domains: dict[str, str] = {
            "prompt": prompt or "",
            "log": log or "",
        }
        for name, mapping in (
            ("tool_args", tool_args),
            ("trace", trace),
            ("event_payload", event_payload),
            ("working_set", working_set),
        ):
            if mapping is not None:
                domains[name] = _flatten(mapping)
        for domain, text in domains.items():
            if self.find_in(text):
                hits.append(domain)
        return hits

    def assert_clean(self, **domains: Any) -> None:
        """若任一域包含凭据则抛出 ``CredentialScanError``。"""
        hits = self.scan(**domains)
        if hits:
            raise CredentialScanError(
                f"credential material detected in: {', '.join(hits)}"
            )


def _flatten(value: Any, prefix: str = "") -> str:
    if isinstance(value, Mapping):
        return " ".join(
            f"{prefix}.{k}={_flatten(v, f'{prefix}.{k}')}" for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v, prefix) for v in value)
    return str(value)


__all__ = ["CredentialScanner", "CredentialScanError"]
