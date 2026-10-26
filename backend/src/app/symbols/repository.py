# 目录仓储协议：描述检查保存、目录增归档和同步任务租约操作；具体事务与竞争控制由仓储实现承担。
# 研究币种目录：公开合约检查通过后登记币种并排队初始同步；研究准入不扩展交易契约。
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.symbols.contracts import CheckResult, ResearchSymbolEntry, SyncRun, SyncSource


# SymbolRepository 定义本领域依赖接口；调用方仅依赖类型契约，外部读写由注入实现负责。
class SymbolRepository(Protocol):
    # 按筛选或归档选项读取领域记录集合/分页结果。
    async def list(self, *, include_archived: bool = False) -> tuple[ResearchSymbolEntry, ...]: ...

    # 按研究标识读取目录条目，不存在时返回空值。
    async def get(self, symbol: str) -> ResearchSymbolEntry | None: ...

    # 保存通过准入检查的研究币种及关键词，并由仓储安排初始同步。
    async def add(
        self, check: CheckResult, *, keywords: tuple[str, ...], now: datetime
    ) -> ResearchSymbolEntry: ...

    # 将领域记录标记为归档，保留历史与审计供读取。
    async def archive(self, symbol: str, *, now: datetime) -> ResearchSymbolEntry: ...

    # 为研究币种排队一个初始公开数据同步任务。
    async def enqueue(self, symbol: str, *, now: datetime) -> SyncRun: ...

    # 按运行标识读取同步任务，不存在时返回空值。
    async def get_run(self, run_id: UUID) -> SyncRun | None: ...

    # 尝试认领一个可处理的同步任务，没有任务时返回空值。
    async def claim(self, *, now: datetime) -> SyncRun | None: ...

    # 尝试续期已认领任务的租约，返回是否成功。
    async def renew(self, run: SyncRun, *, now: datetime) -> bool: ...

    # 按任务所有权写入终态、逐来源结果与快照关联，返回是否更新成功。
    async def finish(
        self,
        run: SyncRun,
        *,
        status: str,
        sources: tuple[SyncSource, ...],
        snapshot_id: UUID | None,
        error: str | None,
        now: datetime,
    ) -> bool: ...

    # 保存公开来源准入检查结果与发生时间。
    async def record_check(self, check: CheckResult, *, now: datetime) -> None: ...
