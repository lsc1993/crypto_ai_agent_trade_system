"""Persist research directory, leased synchronization and append-only associations."""

# ruff: noqa: E501

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_research_symbols"
down_revision: str | None = "0014_report_factors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FORMAT = "symbol ~ '^[A-Z0-9]{1,28}USDT$'"
RESEARCH_TABLES = (
    ("market_candles", "ck_market_candles_symbol"),
    ("derivative_observations", "ck_derivative_observations_symbol"),
    ("market_snapshots", "ck_market_snapshots_symbol"),
    ("market_snapshot_inputs", None),
    ("analysis_reports", "ck_analysis_reports_symbol"),
    ("analysis_evidences", "ck_analysis_evidences_symbol"),
    ("agent_analysis_runs", "ck_agent_runs_symbol"),
    ("harness_runs", "ck_harness_runs_symbol"),
)


def upgrade() -> None:
    symbols = op.create_table(
        "research_symbols",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("base_asset", sa.String(32), nullable=False),
        sa.Column("quote_asset", sa.String(32), nullable=False),
        sa.Column("margin_asset", sa.String(32), nullable=False),
        sa.Column("contract_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(FORMAT, name="ck_research_symbols_format"),
        sa.CheckConstraint("version > 0", name="ck_research_symbols_version"),
        sa.CheckConstraint(
            "quote_asset = 'USDT' AND margin_asset = 'USDT' "
            "AND contract_type = 'PERPETUAL'", name="ck_research_symbols_market"
        ),
    )
    runs = op.create_table(
        "research_symbol_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), sa.ForeignKey("research_symbols.symbol"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("market_snapshots.id")),
        sa.Column("sources", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.String(256)),
        sa.CheckConstraint("status IN ('queued','running','ready','partial','failed','cancelled')", name="ck_research_sync_status"),
        sa.CheckConstraint("version > 0", name="ck_research_sync_version"),
        sa.CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND lease_token IS NULL AND lease_until IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(status IN ('ready','partial','failed','cancelled') AND completed_at IS NOT NULL AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_research_sync_lifecycle",
        ),
    )
    op.create_index("uq_research_sync_active_symbol", "research_symbol_sync_runs", ["symbol"], unique=True, postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index("ix_research_sync_symbol_created", "research_symbol_sync_runs", ["symbol", "created_at"])
    events = op.create_table(
        "research_symbol_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_symbol_sync_runs.id")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_research_symbol_events_scope", "research_symbol_events", ["symbol", "occurred_at"])
    op.create_table(
        "research_news_links",
        sa.Column("news_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("news_items.id"), primary_key=True),
        sa.Column("symbol", sa.String(32), sa.ForeignKey("research_symbols.symbol"), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('asset', 'market_context')", name="ck_research_news_scope"),
    )
    op.create_index("ix_research_news_links_symbol", "research_news_links", ["symbol"])
    now = datetime.now(UTC)
    for base in ("BTC", "ETH"):
        symbol = f"{base}USDT"
        run_id = uuid4()
        op.bulk_insert(symbols, [{
            "symbol": symbol, "base_asset": base, "quote_asset": "USDT", "margin_asset": "USDT",
            "contract_type": "PERPETUAL", "enabled": True, "keywords": [],
            "capabilities": [], "version": 1, "created_at": now, "archived_at": None,
        }])
        op.bulk_insert(runs, [{
            "id": run_id, "symbol": symbol, "version": 1, "status": "queued", "stage": "queued",
            "created_at": now, "sources": [],
        }])
        op.bulk_insert(events, [{
            "id": uuid4(), "operation_id": run_id, "symbol": symbol, "run_id": run_id,
            "kind": "initialized", "occurred_at": now, "payload": {"version": 1},
        }])
    for table, old_check in RESEARCH_TABLES:
        if old_check is not None:
            op.drop_constraint(old_check, table, type_="check")
        op.alter_column(table, "symbol", type_=sa.String(32), existing_type=sa.String(12), existing_nullable=False)
        op.create_check_constraint(f"ck_{table}_research_symbol", table, FORMAT)
        op.create_foreign_key(f"fk_{table}_research_symbol", table, "research_symbols", ["symbol"], ["symbol"])
    # Link historical news without modifying immutable news bodies or evidence hashes.
    op.execute("""
        INSERT INTO research_news_links (news_id, symbol, scope, created_at)
        SELECT n.id, s.symbol,
          CASE WHEN n.event_category IN ('regulation', 'macro') THEN 'market_context' ELSE 'asset' END,
          n.fetched_at
        FROM news_items n JOIN research_symbols s ON n.related_symbols ? s.symbol
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        CREATE FUNCTION prevent_research_history_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'research history is immutable'; END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("research_symbol_events", "research_news_links"):
        op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_research_history_mutation()")
    op.execute("""
        CREATE FUNCTION protect_research_sync_terminal() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR OLD.status IN ('ready','partial','failed','cancelled') THEN
            RAISE EXCEPTION 'terminal research sync is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_research_sync_terminal BEFORE UPDATE OR DELETE ON research_symbol_sync_runs FOR EACH ROW EXECUTE FUNCTION protect_research_sync_terminal()")


def downgrade() -> None:
    raise NotImplementedError("研究币对目录和同步审计不可逆，禁止删除历史数据")
