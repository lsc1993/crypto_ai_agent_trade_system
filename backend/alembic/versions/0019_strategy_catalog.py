# 建立版本化策略目录：稳定策略定义、草稿/发布版本与请求幂等记录。
# 发布版本正文、指纹和发布时间由数据库约束与触发器保护，历史引用不删除。
# 本迁移只新增前向表；不迁移旧报告、不修改业务库真实资金，也不发布任何具体策略。
"""Versioned research strategy catalog tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_strategy_catalog"
down_revision: str | None = "0018_technical_report_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序创建目录表、索引和发布不可变触发器。
def upgrade() -> None:
    op.create_table(
        "strategy_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state_version >= 0", name="ck_strategy_definition_version"),
    )
    op.create_index(
        "ix_strategy_definitions_workspace_created",
        "strategy_definitions",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategy_definitions.id", name="fk_strategy_versions_definition"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('draft','published')", name="ck_strategy_version_state"),
        sa.CheckConstraint("state_version >= 0", name="ck_strategy_version_number"),
        sa.CheckConstraint(
            "(state = 'draft' AND published_at IS NULL) OR "
            "(state = 'published' AND published_at IS NOT NULL AND state_version >= 1)",
            name="ck_strategy_version_published",
        ),
    )
    op.create_index(
        "ix_strategy_versions_workspace_state_published",
        "strategy_versions",
        ["workspace_id", "state", "published_at"],
    )
    op.create_table(
        "strategy_catalog_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('create_draft','update_draft','publish','archive')",
            name="ck_strategy_catalog_request_action",
        ),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_strategy_catalog_request_sha",
        ),
    )
    # 发布行禁止 UPDATE/DELETE；草稿更新和发布状态迁移仍允许。
    op.execute(
        """
        CREATE FUNCTION reject_published_strategy_version_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.state = 'published' THEN
                RAISE EXCEPTION 'published strategy versions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_strategy_versions_immutable
        BEFORE UPDATE OR DELETE ON strategy_versions
        FOR EACH ROW EXECUTE FUNCTION reject_published_strategy_version_mutation();
        """
    )


# 前向迁移明确拒绝回退，避免删除已发布策略版本和用户历史引用。
def downgrade() -> None:
    raise NotImplementedError("版本化策略目录禁止删除")
