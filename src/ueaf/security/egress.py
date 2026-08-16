"""出口 / SSRF 策略：阻止不受信任的对外访问（SEC-014）。

不受信任的工具或生成代码可能尝试访问未列入白名单的目标。``EgressPolicy`` 依据白名单
检查请求的主机/URL，当访问被阻止时生成一条 Security 证据引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class EgressDecision:
    allowed: bool
    target: str
    reason_codes: tuple[str, ...] = ()
    security_evidence_ref: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.allowed


class EgressPolicy:
    """针对不受信任执行的默认拒绝出口白名单（SEC-014）。"""

    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...] = (),
        allowed_schemes: tuple[str, ...] = ("https",),
        block_private_networks: bool = True,
    ) -> None:
        self._allowed_hosts = frozenset(allowed_hosts)
        self._allowed_schemes = frozenset(allowed_schemes)
        self._block_private = block_private_networks

    def evaluate(self, target: str) -> EgressDecision:
        parsed = urlparse(target)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        if scheme not in self._allowed_schemes:
            return EgressDecision(False, target, ("scheme_not_allowed",), "evidence:egress")
        if host and host not in self._allowed_hosts:
            return EgressDecision(False, target, ("host_not_allowlisted",), "evidence:egress")
        if self._block_private and _is_private_host(host):
            return EgressDecision(False, target, ("private_network_blocked",), "evidence:egress")
        return EgressDecision(True, target, ("allowed",))


def _is_private_host(host: str) -> bool:
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    parts = host.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        first = int(parts[0])
        second = int(parts[1])
        if first == 10:
            return True
        if first == 172 and 16 <= second <= 31:
            return True
        if first == 192 and parts[1] == "168":
            return True
    return False


__all__ = ["EgressPolicy", "EgressDecision"]
