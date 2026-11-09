# 声明 C3 本地规划资料的 PostgreSQL ORM 映射。
# 工作台唯一资金池保存共享代次；资料、政策、成本、公开规则和请求结果均为不可变版本。
# 完整财务资料只存受限 JSONB/数值列，不写入通用事件、报告或模型上下文。
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 每工作台固定一个逻辑资金池；generation 随资料、政策或规则变化递增。
class PlanningPoolRecord(Base):
    __tablename__ = "planning_pools"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_planning_pools_workspace"),
        CheckConstraint("generation >= 0", name="ck_planning_pool_generation"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 用户资料不可变版本；document 保存完整本地财务资料，costs_ref 指向独立成本版本。
class PlanningProfileRecord(Base):
    __tablename__ = "planning_profiles"
    __table_args__ = (
        CheckConstraint("pool_generation >= 0", name="ck_planning_profile_generation"),
        CheckConstraint("char_length(sha256) = 64", name="ck_planning_profile_sha"),
        CheckConstraint("expires_at > declared_at", name="ck_planning_profile_expiry"),
        Index(
            "ix_planning_profiles_workspace_generation",
            "workspace_id",
            "pool_generation",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_pools.id", name="fk_planning_profiles_pool"),
        nullable=False,
    )
    pool_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 用户明确确认的风险政策版本；缺项政策仍保存为不可变版本但不产生完整引用。
class PlanningRiskPolicyRecord(Base):
    __tablename__ = "planning_risk_policies"
    __table_args__ = (
        CheckConstraint("pool_generation >= 0", name="ck_planning_policy_generation"),
        CheckConstraint("char_length(sha256) = 64", name="ck_planning_policy_sha"),
        Index(
            "ix_planning_risk_policies_workspace_generation",
            "workspace_id",
            "pool_generation",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_pools.id", name="fk_planning_policies_pool"),
        nullable=False,
    )
    pool_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 成本资料不可变版本；profile 通过 costs_ref 关联，不把成本写回已审计划。
class PlanningCostRecord(Base):
    __tablename__ = "planning_costs"
    __table_args__ = (
        CheckConstraint("pool_generation >= 0", name="ck_planning_cost_generation"),
        CheckConstraint("char_length(sha256) = 64", name="ck_planning_cost_sha"),
        CheckConstraint("expires_at > declared_at", name="ck_planning_cost_expiry"),
        Index(
            "ix_planning_costs_workspace_generation",
            "workspace_id",
            "pool_generation",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    pool_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_pools.id", name="fk_planning_costs_pool"),
        nullable=False,
    )
    pool_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 公开规则不可变版本；symbol/venue 列用于按产品读取最新快照，正文仍以 JSONB 指纹为准。
class PlanningVenueRuleRecord(Base):
    __tablename__ = "planning_venue_rules"
    __table_args__ = (
        CheckConstraint("pool_generation >= 0", name="ck_planning_venue_rule_generation"),
        CheckConstraint("char_length(sha256) = 64", name="ck_planning_venue_rule_sha"),
        CheckConstraint("expires_at > observed_at", name="ck_planning_venue_rule_expiry"),
        Index(
            "ix_planning_venue_rules_workspace_product_generation",
            "workspace_id",
            "venue",
            "symbol",
            "pool_generation",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    pool_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 请求幂等记录保存规范化请求指纹和已提交结果；同一 request_id 只能对应同一操作/内容。
class PlanningInputRequestRecord(Base):
    __tablename__ = "planning_input_requests"
    __table_args__ = (
        CheckConstraint(
            "action IN ('create_profile','create_policy','refresh_venue_rules')",
            name="ck_planning_input_request_action",
        ),
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_planning_input_request_sha",
        ),
        Index("ix_planning_input_requests_workspace", "workspace_id", "created_at"),
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
