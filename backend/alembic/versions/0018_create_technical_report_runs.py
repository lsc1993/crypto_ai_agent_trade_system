# 建立手动请求的持久化技术研究队列及请求幂等映射。
# 单例队列行用于执行协调，活动币种唯一索引和状态约束保护任务生命周期。
# 报告关联、失败错误和租约字段随状态受约束，不表示定时研究或自动交易。
"""Durable manually requested technical research queue."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_technical_report_runs"
down_revision: str | None = "0017_technical_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 单例行是事务锁的共同锚点，容量检查与任务领取据此串行协调。
    op.create_table(
        "technical_report_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="ck_technical_queue_singleton"),
    )
    op.execute("INSERT INTO technical_report_queue (id) VALUES (1)")
    # 可变任务状态与不可变报告分开；终态、错误和租约字段必须一致。
    op.create_table(
        "technical_report_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("owner", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("technical_reports.id")
        ),
        sa.Column("error_code", sa.String(32)),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','degraded','failed')",
            name="ck_technical_run_status",
        ),
        sa.CheckConstraint(
            "phase IN ('queued','collecting','analyzing','validating',"
            "'composing','saving','finished')",
            name="ck_technical_run_phase",
        ),
        sa.CheckConstraint(
            "(status IN ('completed','degraded','failed')) = "
            "(finished_at IS NOT NULL AND phase = 'finished')",
            name="ck_technical_run_terminal",
        ),
        sa.CheckConstraint(
            "(status IN ('completed','degraded')) = (report_id IS NOT NULL)",
            name="ck_technical_run_report",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)", name="ck_technical_run_error"
        ),
        sa.CheckConstraint(
            "(status = 'running') = (owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_technical_run_lease",
        ),
    )
    op.create_index(
        "uq_technical_run_active_symbol",
        "technical_report_runs",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index("ix_technical_run_created", "technical_report_runs", ["created_at", "id"])
    # 请求 UUID 映射已存在运行，重放请求不应再次生成研究报告。
    op.create_table(
        "technical_report_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technical_report_runs.id"),
            nullable=False,
        ),
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("技术研究任务和审计历史禁止删除")
