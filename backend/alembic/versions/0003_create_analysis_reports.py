# 建立确定性研究报告与冻结证据存储。
# 外键关联报告和证据；不可变触发器在数据库层拒绝后续改写。
"""Create immutable deterministic market research report tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_create_analysis_reports"
down_revision: str | None = "0002_create_market_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 报告表保留生成状态与确定性结论，证据由关联表单独保存。
    op.create_table(
        "analysis_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("inferences", postgresql.JSONB(), nullable=False),
        sa.Column("risks", postgresql.JSONB(), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_analysis_reports_symbol"
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'degraded')", name="ck_analysis_reports_status"
        ),
        sa.CheckConstraint(
            "data_cutoff_at IS NULL OR data_cutoff_at <= generated_at",
            name="ck_analysis_reports_cutoff",
        ),
    )
    op.create_index(
        "ix_analysis_reports_symbol_created_at",
        "analysis_reports",
        ["symbol", sa.text("created_at DESC")],
    )
    op.create_index("ix_analysis_reports_status", "analysis_reports", ["status"])

    # 载荷、来源及哈希与报告关联，报告冻结后不可重新解释证据。
    op.create_table(
        "analysis_evidences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_report_id"], ["analysis_reports.id"], name="fk_analysis_evidences_report"
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_analysis_evidences_symbol"
        ),
        sa.CheckConstraint(
            "fetched_at >= observed_at", name="ck_analysis_evidences_time_order"
        ),
        sa.CheckConstraint(
            "char_length(payload_sha256) = 64", name="ck_analysis_evidences_hash_length"
        ),
        sa.CheckConstraint(
            "octet_length(payload::text) <= 65536", name="ck_analysis_evidences_payload_size"
        ),
    )
    op.create_index(
        "ix_analysis_evidences_report_id",
        "analysis_evidences",
        ["analysis_report_id"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_analysis_record_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'analysis records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_analysis_reports_immutable
        BEFORE UPDATE OR DELETE ON analysis_reports
        FOR EACH ROW EXECUTE FUNCTION prevent_analysis_record_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_analysis_evidences_immutable
        BEFORE UPDATE OR DELETE ON analysis_evidences
        FOR EACH ROW EXECUTE FUNCTION prevent_analysis_record_mutation();
        """
    )


# 历史脚本保留回退实现，仅解释其行为；日常维护不得对业务库执行删表回退。
def downgrade() -> None:
    op.execute("DROP TRIGGER trg_analysis_evidences_immutable ON analysis_evidences")
    op.execute("DROP TRIGGER trg_analysis_reports_immutable ON analysis_reports")
    op.execute("DROP FUNCTION prevent_analysis_record_mutation")
    op.drop_index("ix_analysis_evidences_report_id", table_name="analysis_evidences")
    op.drop_table("analysis_evidences")
    op.drop_index("ix_analysis_reports_status", table_name="analysis_reports")
    op.drop_index("ix_analysis_reports_symbol_created_at", table_name="analysis_reports")
    op.drop_table("analysis_reports")
