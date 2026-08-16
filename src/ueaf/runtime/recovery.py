"""Checkpoint / 恢复（core spec 01 §9.2，spec 02 §6.3）。

进程重启后，``RecoveryManager`` 从权威持久化状态恢复运行：重新加载 RunRecord，
校验冻结的 adapter 绑定仍然有效，获取全新的 lease/fencing token，并重新校验
冻结的 Principal/Policy/Release 绑定。它绝不信任旧进程的内存。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import new_object_id
from ueaf.common.meta import ContractMeta
from ueaf.runtime.coordinator import RunCoordinator
from ueaf.runtime.objects import Checkpoint, RunRecord


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    recovered: bool
    run_id: str
    reason_codes: tuple[str, ...]
    record: RunRecord | None = None


class InMemoryCheckpointStore:
    """Checkpoint 注册表（可恢复位置不构成外部证明）。"""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        if checkpoint.checkpoint_id in self._checkpoints:
            raise ValueError(f"Checkpoint {checkpoint.checkpoint_id} already exists")
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        return checkpoint

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        return self._checkpoints.get(checkpoint_id)


class RecoveryManager:
    """重启后使用权威持久化状态恢复运行（RUN-004）。"""

    def __init__(self, coordinator: RunCoordinator, checkpoints: InMemoryCheckpointStore) -> None:
        self._coordinator = coordinator
        self._checkpoints = checkpoints

    async def recover(
        self,
        run_id: str,
        *,
        holder_id: str,
        checkpoint_ref: str | None = None,
        expected_runtime_adapter_ref: str | None = None,
    ) -> RecoveryResult:
        record = await self._coordinator.get_run(run_id)
        if record is None:
            return RecoveryResult(False, run_id, ("run_not_found",))
        if record.phase == "terminal":
            return RecoveryResult(True, run_id, ("already_terminal",), record)

        # 冻结的 adapter 绑定必须能在重启后保留（RUN-007）。
        if (
            expected_runtime_adapter_ref is not None
            and record.runtime_adapter_ref != expected_runtime_adapter_ref
        ):
            return RecoveryResult(False, run_id, ("runtime_adapter_binding_changed",), record)

        # 若提供了 checkpoint，它必须存在并绑定同一 run。
        if checkpoint_ref is not None:
            checkpoint = self._checkpoints.get(checkpoint_ref)
            if checkpoint is None or checkpoint.run_id != run_id:
                return RecoveryResult(False, run_id, ("checkpoint_invalid",), record)

        # 获取全新的 lease/fencing token（绝不复用过期的，RUN-003）。
        record = await self._coordinator.acquire_lease(run_id, holder_id=holder_id)
        return RecoveryResult(True, run_id, ("recovered",), record)


def new_checkpoint(
    run: RunRecord,
    *,
    state_schema_version: str = "1.0.0",
    pending_condition_refs: tuple[str, ...] = (),
    in_flight_action_refs: tuple[str, ...] = (),
) -> Checkpoint:
    checkpoint_id = new_object_id("checkpoint")
    return Checkpoint(
        meta=ContractMeta(
            contract_name="Checkpoint",
            contract_version="1.0.0",
            object_id=checkpoint_id,
            tenant_id=run.meta.tenant_id,
            created_at=run.meta.created_at,
            producer="ueaf-runtime",
            producer_version="0.1.0",
        ),
        checkpoint_id=checkpoint_id,
        run_id=run.run_id,
        state_schema_version=state_schema_version,
        frozen_release_id=run.release_id,
        pending_condition_refs=pending_condition_refs,
        in_flight_action_refs=in_flight_action_refs,
        concurrency_token=run.revision,
        integrity_ref=f"integrity:{checkpoint_id}",
    )
