"""召回投影（功能模块 04 §5.1 第 7 点 / §5.3 / §7）。

按 subject/scope/purpose/有效期过滤；被 superseded/deleted/expired 的记录绝不命中
（RAG-008：已删除来源消失）。支持 team/tenant 级 scope 匹配（§7 多租户）。删除传播：
删除覆盖权威 Store 与检索投影（§5.3 / RAG-007）——投影始终读取权威 Store，被标记
deleted 的记录自动不再命中。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ueaf.common.identifiers import utcnow
from ueaf.memory.objects import MemoryRecord

TEAM_TENANT_SCOPES = ("team", "tenant")


class MemoryStoreProtocol(Protocol):
    """召回投影所需的只读 Store 视图。"""

    def get(self, record_id: str) -> MemoryRecord | None: ...

    def all_records(self) -> tuple[MemoryRecord, ...]: ...


@dataclass(slots=True)
class RecallProjection:
    """受治理记忆的召回投影：命中过滤 + team/tenant 支持 + 删除传播。"""

    store: MemoryStoreProtocol

    def recall(
        self,
        subject_ref: str,
        *,
        scope: str | None = None,
        purpose: str | None = None,
        moment: datetime | None = None,
        include_team_tenant: bool = False,
        consent_ref: str | None = None,
        authorized_team_refs: tuple[str, ...] = (),
        authorized_tenant_ref: str | None = None,
    ) -> list[MemoryRecord]:
        """召回命中记录；仅 active 且在有效期内的记录可命中（§5.1 第 7 点）。

        ``purpose`` 过滤按 ``record.scope`` 精确匹配：当前 ``MemoryRecord.scope`` 在
        晋升时承载来源 purpose（``promote`` 映射），因此 purpose 参数复用 scope 语义
        （§5.1 第 7 点按 subject/scope/purpose 过滤）。

        团队/租户级记忆（M3）：``include_team_tenant=True`` 时，仅当调用方声明其
        授权团队（``authorized_team_refs``）或授权租户（``authorized_tenant_ref``）
        与记录的 ``scope`` 匹配才命中；未授权绝不返回 team/tenant 记录（§7 要求
        tenant/principal 贯穿查询）。调用方必须在授权层完成成员/租户身份校验后传入。
        """
        moment = moment or utcnow()
        hits: list[MemoryRecord] = []
        for record in self.store.all_records():
            if record.status != "active":
                continue
            if not (record.valid_from <= moment and (
                record.expires_at is None or moment < record.expires_at
            )):
                continue
            subject_match = record.subject_ref == subject_ref
            if not subject_match and include_team_tenant and record.scope in TEAM_TENANT_SCOPES:
                # M3：team/tenant 记录必须由调用方授权身份背书。
                if record.scope == "team" and record.subject_ref not in authorized_team_refs:
                    continue
                if record.scope == "tenant" and record.subject_ref != authorized_tenant_ref:
                    continue
                subject_match = True
            if not subject_match:
                continue
            if scope is not None and record.scope != scope:
                continue
            if purpose is not None and record.scope != purpose:
                continue
            if consent_ref is not None and record.consent_ref != consent_ref:
                continue
            hits.append(record)
        return hits


__all__ = ["MemoryStoreProtocol", "RecallProjection", "TEAM_TENANT_SCOPES"]
