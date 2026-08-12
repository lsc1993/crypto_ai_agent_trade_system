"""Create immutable news cache, agent runs, and agent report details."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_create_agent_research"
down_revision: str | None = "0007_paper_account_valuations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("deduplication_key", sa.String(length=2000), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_tier", sa.String(length=32), nullable=False),
        sa.Column("source_item_id", sa.String(length=300), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.String(length=1600), nullable=False),
        sa.Column("related_symbols", postgresql.JSONB(), nullable=False),
        sa.Column("event_category", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "deduplication_key",
            name="uq_news_items_deduplication_key",
        ),
        sa.CheckConstraint(
            "source_tier IN ('primary', 'professional_media')",
            name="ck_news_items_source_tier",
        ),
        sa.CheckConstraint("language = 'en'", name="ck_news_items_english"),
        sa.CheckConstraint(
            "fetched_at >= published_at",
            name="ck_news_items_time_order",
        ),
        sa.CheckConstraint(
            "event_category IN ('market', 'regulation', 'etf', 'security', 'protocol', 'macro')",
            name="ck_news_items_event_category",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_news_items_hash_length",
        ),
    )
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])

    op.create_table(
        "agent_analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generator_kind", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_reports.analysis_id"],
            name="fk_agent_runs_analysis",
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')",
            name="ck_agent_runs_symbol",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'degraded')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "generator_kind = 'langgraph_deepseek'",
            name="ck_agent_runs_generator_kind",
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name="ck_agent_runs_time_order",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z0-9_]+$'",
            name="ck_agent_runs_error_code",
        ),
    )
    op.create_index(
        "ix_agent_analysis_runs_symbol_completed_at",
        "agent_analysis_runs",
        ["symbol", "completed_at"],
    )

    op.create_table(
        "agent_report_details",
        sa.Column("analysis_report_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("horizon", sa.String(length=32), nullable=False),
        sa.Column("outlook", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("trend_alignment", postgresql.JSONB(), nullable=False),
        sa.Column("support_zones", postgresql.JSONB(), nullable=False),
        sa.Column("resistance_zones", postgresql.JSONB(), nullable=False),
        sa.Column("catalysts", postgresql.JSONB(), nullable=False),
        sa.Column("risks_and_invalidation", postgresql.JSONB(), nullable=False),
        sa.Column("data_quality", postgresql.JSONB(), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_report_id"],
            ["analysis_reports.id"],
            name="fk_agent_report_details_report",
        ),
        sa.CheckConstraint(
            "horizon = '1_to_3_days'",
            name="ck_agent_report_details_horizon",
        ),
        sa.CheckConstraint(
            "outlook IN ('bullish', 'bearish', 'neutral')",
            name="ck_agent_report_details_outlook",
        ),
        sa.CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_agent_report_details_confidence",
        ),
    )

    _install_immutable_trigger(
        table_name="news_items",
        function_name="prevent_news_item_mutation",
        trigger_name="trg_news_items_immutable",
    )
    _install_immutable_trigger(
        table_name="agent_analysis_runs",
        function_name="prevent_agent_run_mutation",
        trigger_name="trg_agent_analysis_runs_immutable",
    )
    _install_immutable_trigger(
        table_name="agent_report_details",
        function_name="prevent_agent_report_detail_mutation",
        trigger_name="trg_agent_report_details_immutable",
    )


def _install_immutable_trigger(
    *,
    table_name: str,
    function_name: str,
    trigger_name: str,
) -> None:
    op.execute(
        f"""
        CREATE FUNCTION {function_name}() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'analysis records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}();
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Agent 研究持久化迁移不可逆，禁止删除审计记录")
