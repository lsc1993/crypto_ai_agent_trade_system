# 建立本地手动规划资料表：单工作台资金池、资料/政策/成本/公开规则版本与请求幂等记录。
# 本迁移只新增前向表、索引和不可变触发器；不迁移业务库、不写入用户财务资料、不扩展交易权限。
# 版本行和请求结果不可 UPDATE/DELETE；资金池只允许代次递增，删除池会破坏版本引用。
# 0021 尚未应用到任何业务库；回退会删除本地规划历史，因此明确拒绝。
"""Local planning inputs and public venue rule snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_planning_inputs"
down_revision: str | None = "0020_research_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序创建资金池、不可变输入版本和请求幂等表。
def upgrade() -> None:
    op.create_table(
        "planning_pools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", name="uq_planning_pools_workspace"),
        sa.CheckConstraint("generation >= 0", name="ck_planning_pool_generation"),
    )

    op.create_table(
        "planning_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planning_pools.id", name="fk_planning_profiles_pool"),
            nullable=False,
        ),
        sa.Column("pool_generation", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_generation >= 0", name="ck_planning_profile_generation"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_planning_profile_sha"),
        sa.CheckConstraint("expires_at > declared_at", name="ck_planning_profile_expiry"),
    )
    op.create_index(
        "ix_planning_profiles_workspace_generation",
        "planning_profiles",
        ["workspace_id", "pool_generation"],
    )

    op.create_table(
        "planning_risk_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planning_pools.id", name="fk_planning_policies_pool"),
            nullable=False,
        ),
        sa.Column("pool_generation", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_generation >= 0", name="ck_planning_policy_generation"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_planning_policy_sha"),
    )
    op.create_index(
        "ix_planning_risk_policies_workspace_generation",
        "planning_risk_policies",
        ["workspace_id", "pool_generation"],
    )

    op.create_table(
        "planning_costs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("planning_pools.id", name="fk_planning_costs_pool"),
            nullable=False,
        ),
        sa.Column("pool_generation", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_generation >= 0", name="ck_planning_cost_generation"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_planning_cost_sha"),
        sa.CheckConstraint("expires_at > declared_at", name="ck_planning_cost_expiry"),
    )
    op.create_index(
        "ix_planning_costs_workspace_generation",
        "planning_costs",
        ["workspace_id", "pool_generation"],
    )

    op.create_table(
        "planning_venue_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("pool_generation", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pool_generation >= 0", name="ck_planning_venue_rule_generation"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_planning_venue_rule_sha"),
        sa.CheckConstraint("expires_at > observed_at", name="ck_planning_venue_rule_expiry"),
    )
    op.create_index(
        "ix_planning_venue_rules_workspace_product_generation",
        "planning_venue_rules",
        ["workspace_id", "venue", "symbol", "pool_generation"],
    )

    op.create_table(
        "planning_input_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('create_profile','create_policy','refresh_venue_rules')",
            name="ck_planning_input_request_action",
        ),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_planning_input_request_sha",
        ),
    )
    op.create_index(
        "ix_planning_input_requests_workspace",
        "planning_input_requests",
        ["workspace_id", "created_at"],
    )

    # 版本行和请求结果是冻结证据；任何 UPDATE/DELETE 都拒绝，保留历史引用链。
    op.execute(
        """
        CREATE FUNCTION reject_planning_version_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'planning versions are immutable';
        END;
        $$;
        """
    )
    for table in (
        "planning_profiles",
        "planning_risk_policies",
        "planning_costs",
        "planning_venue_rules",
        "planning_input_requests",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_planning_version_mutation();
            """
        )

    # 资金池允许代次更新，但禁止删除，避免历史版本失去池归属和代次依据。
    op.execute(
        """
        CREATE FUNCTION reject_planning_pool_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'planning pool is immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_planning_pools_no_delete
        BEFORE DELETE ON planning_pools
        FOR EACH ROW EXECUTE FUNCTION reject_planning_pool_delete();
        """
    )


# 前向迁移拒绝回退，避免删除本地规划版本和请求幂等记录。
def downgrade() -> None:
    raise NotImplementedError("本地规划资料迁移不可逆，禁止删除历史版本")
