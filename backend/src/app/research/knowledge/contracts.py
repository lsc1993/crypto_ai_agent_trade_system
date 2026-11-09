# 定义关键词知识库的不可变公共契约：导入、版本、查询、命中与稳定错误码。
# 正文只作为数据保存和返回，不能触发工具、权限变化或交易动作；所有时间必须为 UTC。
# 版本内容哈希覆盖文档身份、标题、来源、范围、权限、原文指纹和用户声明时间，
# 不覆盖服务端首次可得/发布时间，历史可得性始终由服务端时间单独判断。
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.research.knowledge.indexing import (
    MAX_DOCUMENT_BYTES,
    MAX_QUERY_TERMS,
    chunk_text,
    sha256_text,
    tokenize,
)
from app.shared.agent_types import (
    AgentModel,
    JsonObject,
    UtcDateTime,
    VersionRef,
    is_sha256,
    require_utc,
    sha256_json,
)

_SCOPE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_MAX_QUERY_CHARS = 2000


# 知识契约错误携带稳定原因码；Pydantic 会把字段校验失败包装为 ValidationError。
class KnowledgeContractError(ValueError):
    def __init__(self, message: str, *, code: str = "knowledge_contract_violation") -> None:
        super().__init__(message)
        self.code = code


class KnowledgeConflictError(KnowledgeContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="knowledge_conflict")


class KnowledgeNotAvailableError(KnowledgeContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="knowledge_not_available")


class KnowledgeIntegrityError(KnowledgeContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="knowledge_integrity_violation")


class KnowledgeQueryError(KnowledgeContractError):
    def __init__(self, message: str, *, code: str = "knowledge_query_invalid") -> None:
        super().__init__(message, code=code)


class KnowledgeIndexError(KnowledgeContractError):
    def __init__(self, message: str, *, code: str = "knowledge_index_unavailable") -> None:
        super().__init__(message, code=code)


# 版本状态区分未发布草稿与可检索发布版本；停用是文档级状态，不删除历史版本。
class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


# 首期只有单用户工作台权限；workspace_id 是实际隔离边界，不允许按正文内容提权。
class KnowledgeAccess(StrEnum):
    WORKSPACE = "workspace"


# 适用范围使用稳定小写标识，避免自由文本造成无法复现的过滤条件。
def validate_scope(value: str) -> str:
    normalized = value.strip()
    if _SCOPE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("知识适用范围必须是有界小写标识")
    return normalized


# 校验非空、UTF-8 字节不超限且未被规范化的原始正文。
def _validate_text(value: str) -> str:
    if not value.strip():
        raise ValueError("知识正文不能为空")
    if len(value.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValueError("知识正文超过 256 KiB 上限")
    return value


# 校验标题/来源并去除首尾空白；正文不做 strip，以免改变原文分块和指纹。
def _validate_label(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("知识标题或来源不能为空")
    return normalized


# 导入草稿只接受显式文本字段；不接收 URL、文件路径、附件或抓取目标。
class KnowledgeImport(AgentModel):
    document_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=500)
    scope: str = Field(min_length=1, max_length=64)
    access: KnowledgeAccess = KnowledgeAccess.WORKSPACE
    declared_published_at: UtcDateTime | None = None

    @field_validator("title", "source")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return _validate_label(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("scope")
    @classmethod
    def validate_scope_value(cls, value: str) -> str:
        return validate_scope(value)

    @field_validator("declared_published_at")
    @classmethod
    def validate_declared_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)


# 不可变知识版本；正文、指纹和来源时间在发布前后都不允许改写。
class KnowledgeVersion(AgentModel):
    ref: VersionRef
    document_id: UUID
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=500)
    scope: str = Field(min_length=1, max_length=64)
    access: KnowledgeAccess
    text: str = Field(min_length=1)
    text_sha256: str
    chunk_count: int = Field(ge=1)
    first_available_at: UtcDateTime
    declared_published_at: UtcDateTime | None = None
    status: KnowledgeStatus
    state_version: int = Field(ge=0)
    published_at: UtcDateTime | None = None
    archived: bool = False
    archived_at: UtcDateTime | None = None

    @field_validator("title", "source")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return _validate_label(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("scope")
    @classmethod
    def validate_scope_value(cls, value: str) -> str:
        return validate_scope(value)

    @field_validator("text_sha256")
    @classmethod
    def validate_text_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("知识原文指纹必须是 64 位小写十六进制")
        return value

    @field_validator("first_available_at", "declared_published_at", "published_at", "archived_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    # 逐项重算原文、分块数、内容指纹和服务端时间关系，拒绝“正文变了但旧 ref 仍有效”。
    @model_validator(mode="after")
    def validate_version(self) -> KnowledgeVersion:
        if self.text_sha256 != knowledge_text_sha256(self.text):
            raise ValueError("知识原文指纹与正文不一致")
        expected_sha256 = knowledge_content_sha256(
            document_id=self.document_id,
            title=self.title,
            source=self.source,
            scope=self.scope,
            access=self.access,
            text_sha256=self.text_sha256,
            declared_published_at=self.declared_published_at,
        )
        if self.ref.sha256 != expected_sha256:
            raise ValueError("知识版本指纹与内容不一致")
        if self.chunk_count != len(chunk_text(self.text)):
            raise ValueError("知识分块数量与正文不一致")
        if (
            self.declared_published_at is not None
            and self.declared_published_at > self.first_available_at
        ):
            raise ValueError("用户声明发布时间不能晚于服务端首次可得时间")
        if self.status is KnowledgeStatus.DRAFT:
            if self.state_version != 0 or self.published_at is not None:
                raise ValueError("草稿版本代次必须为零且不能有发布时间")
        else:
            if self.state_version < 1 or self.published_at is None:
                raise ValueError("发布版本必须有发布代次和发布时间")
            if self.published_at < self.first_available_at:
                raise ValueError("发布时间不能早于首次可得时间")
        if self.archived != (self.archived_at is not None):
            raise ValueError("归档状态与归档时间必须一致")
        return self

    # 从导入草稿冻结不可变版本；服务端首次可得时间由调用方提供，内容哈希不包含它。
    @classmethod
    def build(
        cls,
        *,
        version_id: UUID,
        document_id: UUID,
        draft: KnowledgeImport,
        first_available_at: datetime,
        status: KnowledgeStatus = KnowledgeStatus.DRAFT,
        state_version: int = 0,
        published_at: datetime | None = None,
        archived: bool = False,
        archived_at: datetime | None = None,
    ) -> KnowledgeVersion:
        text_sha256 = knowledge_text_sha256(draft.text)
        return cls(
            ref=VersionRef(
                version_id=version_id,
                sha256=knowledge_content_sha256(
                    document_id=document_id,
                    title=draft.title,
                    source=draft.source,
                    scope=draft.scope,
                    access=draft.access,
                    text_sha256=text_sha256,
                    declared_published_at=draft.declared_published_at,
                ),
            ),
            document_id=document_id,
            title=draft.title,
            source=draft.source,
            scope=draft.scope,
            access=draft.access,
            text=draft.text,
            text_sha256=text_sha256,
            chunk_count=len(chunk_text(draft.text)),
            first_available_at=first_available_at,
            declared_published_at=draft.declared_published_at,
            status=status,
            state_version=state_version,
            published_at=published_at,
            archived=archived,
            archived_at=archived_at,
        )


# 检索查询只接受有界文本；未来截至时间由服务层和仓储结合服务端时钟拒绝。
class KnowledgeQuery(AgentModel):
    text: str = Field(min_length=1, max_length=_MAX_QUERY_CHARS)
    scope: str | None = Field(default=None, max_length=64)
    as_of: UtcDateTime | None = None
    access: KnowledgeAccess = KnowledgeAccess.WORKSPACE

    @field_validator("text")
    @classmethod
    def validate_query_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("知识查询不能为空")
        terms = tokenize(value)
        if not terms:
            raise ValueError("知识查询没有可检索的中英文词项")
        if len(terms) > MAX_QUERY_TERMS:
            raise ValueError("知识查询去重词项不能超过 64 个")
        return value

    @field_validator("scope")
    @classmethod
    def validate_scope_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_scope(value)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    # 查询词项是确定性派生值，不作为可写字段进入 JSON；调用方不能注入额外检索词。
    @property
    def terms(self) -> tuple[str, ...]:
        return tokenize(self.text)


# 单个命中块绑定文档/版本/块标识、原文片段、来源时间和整数分数。
# 命中文本仍是非可信数据；调用方不得把其中内容解释为系统指令或权限依据。
class KnowledgeHit(AgentModel):
    document_id: UUID
    version_ref: VersionRef
    chunk_id: UUID
    chunk_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=500)
    scope: str = Field(min_length=1, max_length=64)
    first_available_at: UtcDateTime
    declared_published_at: UtcDateTime | None = None
    published_at: UtcDateTime
    chunk_sha256: str
    score: int = Field(ge=1)

    @field_validator("title", "source")
    @classmethod
    def strip_label(cls, value: str) -> str:
        return _validate_label(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value:
            raise ValueError("命中片段不能为空")
        return value

    @field_validator("scope")
    @classmethod
    def validate_scope_value(cls, value: str) -> str:
        return validate_scope(value)

    @field_validator("chunk_sha256")
    @classmethod
    def validate_chunk_sha256(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("命中片段指纹必须是 64 位小写十六进制")
        return value

    @field_validator("first_available_at", "declared_published_at", "published_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @model_validator(mode="after")
    def validate_hit(self) -> KnowledgeHit:
        if self.chunk_sha256 != knowledge_text_sha256(self.text):
            raise ValueError("命中片段指纹与正文不一致")
        if self.published_at < self.first_available_at:
            raise ValueError("命中发布时间不能早于首次可得时间")
        return self


# 计算原文 UTF-8 指纹；用于版本正文和命中片段完整性校验。
def knowledge_text_sha256(text: str) -> str:
    return sha256_text(text)


# 计算版本内容指纹；字段使用驼峰 JSON 键并按键排序，保证跨进程稳定。
def knowledge_content_sha256(
    *,
    document_id: UUID,
    title: str,
    source: str,
    scope: str,
    access: KnowledgeAccess,
    text_sha256: str,
    declared_published_at: datetime | None,
) -> str:
    payload: JsonObject = {
        "documentId": str(document_id),
        "title": title,
        "source": source,
        "scope": scope,
        "access": access.value,
        "textSha256": text_sha256,
        "declaredPublishedAt": (
            None if declared_published_at is None else declared_published_at.isoformat()
        ),
    }
    return sha256_json(payload)


__all__ = [
    "KnowledgeAccess",
    "KnowledgeConflictError",
    "KnowledgeContractError",
    "KnowledgeHit",
    "KnowledgeImport",
    "KnowledgeIndexError",
    "KnowledgeIntegrityError",
    "KnowledgeNotAvailableError",
    "KnowledgeQuery",
    "KnowledgeQueryError",
    "KnowledgeStatus",
    "KnowledgeVersion",
    "knowledge_content_sha256",
    "knowledge_text_sha256",
    "validate_scope",
]
