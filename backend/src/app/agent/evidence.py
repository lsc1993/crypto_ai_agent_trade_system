# 保存单次请求内共享的冻结公开证据，区分可传给模型的内容与待保存的原始载荷。
# 来源、观测和抓取时间随证据一起保留；冻结数据类阻止字段重绑定，嵌套字典仍需调用方保持不变。
"""Request-local immutable evidence shared by fixed public collection paths."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue

from app.agent.model import ModelEvidenceKind


# 同一证据标识贯穿模型引用与报告保存；内容和载荷不得混入检查点或普通日志。
@dataclass(frozen=True)
class FrozenResearchEvidence:
    id: UUID
    kind: ModelEvidenceKind
    source: str
    source_url: str
    observed_at: datetime
    fetched_at: datetime
    summary: str
    content: str
    payload: dict[str, JsonValue]
