"""受治理的记忆领域（功能模块 04）。

记忆绝不由模型直接写入；``MemoryRecord`` 只能由受治理的 ``MemoryCandidate`` 对象或权威
同步创建，敏感条目需要同意（consent）。公开：规范对象、治理服务、候选评审、召回投影、
使用审计与治理结果。
"""

from ueaf.memory.governance import MemoryGovernanceRules, RetentionDecision, RetentionPolicy
from ueaf.memory.memory_audit import MemoryAudit, RecallUsage
from ueaf.memory.memory_recall import RecallProjection
from ueaf.memory.objects import MemoryCandidate, MemoryRecord
from ueaf.memory.resolution import MemoryResolution
from ueaf.memory.review import CandidateReview, CandidateReviewGate
from ueaf.memory.service import (
    InMemoryMemoryStore,
    MemoryGovernanceError,
    MemoryService,
)

__all__ = [
    "CandidateReview",
    "CandidateReviewGate",
    "InMemoryMemoryStore",
    "MemoryAudit",
    "MemoryCandidate",
    "MemoryGovernanceError",
    "MemoryGovernanceRules",
    "MemoryRecord",
    "MemoryResolution",
    "MemoryService",
    "RecallProjection",
    "RecallUsage",
    "RetentionDecision",
    "RetentionPolicy",
]

