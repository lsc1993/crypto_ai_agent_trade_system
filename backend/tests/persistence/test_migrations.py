import asyncio
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from importlib import import_module
from importlib.util import find_spec, module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from alembic import command
from app.shared.config import AppSettings

PAPER_TEST_NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
AGENT_TEST_NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
HARNESS_TEST_NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_database_engine_factory_uses_an_asyncpg_postgresql_url() -> None:
    assert find_spec("app.shared.database") is not None
    database = import_module("app.shared.database")
    factory = database.create_async_engine_from_secret
    engine = factory(
        SecretStr("postgresql+asyncpg://user:password@localhost/research"),
    )

    try:
        assert engine.url.get_backend_name() == "postgresql"
        assert engine.url.get_driver_name() == "asyncpg"
    finally:
        await engine.dispose()


def test_alembic_upgrade_creates_its_version_table_in_an_isolated_schema() -> None:
    database = import_module("app.shared.database")
    upgrade_database = getattr(database, "upgrade_database", None)

    assert callable(upgrade_database)
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        upgrade_database(test_database_url, schema=schema)
        assert asyncio.run(_version_table_schemas(test_database_url)) == [schema]
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_market_migration_creates_numeric_candle_columns_and_unique_key() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        database = import_module("app.shared.database")
        database.upgrade_database(test_database_url, schema=schema)
        columns = asyncio.run(_table_column_types(test_database_url, schema, "market_candles"))
        constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "market_candles")
        )

        assert columns["close_price"] == "numeric"
        assert columns["open_at"] == "timestamp with time zone"
        assert ("UNIQUE", ("symbol", "timeframe", "open_at")) in constraints
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_backtest_migration_creates_immutable_numeric_snapshot_tables() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"market_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        database = import_module("app.shared.database")
        database.upgrade_database(test_database_url, schema=schema)
        runs = asyncio.run(_table_column_types(test_database_url, schema, "backtest_runs"))
        candles = asyncio.run(
            _table_column_types(test_database_url, schema, "backtest_candles")
        )
        events = asyncio.run(_table_column_types(test_database_url, schema, "backtest_events"))
        candle_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "backtest_candles")
        )
        event_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "backtest_events")
        )

        assert runs["initial_cash"] == "numeric"
        assert candles["close_price"] == "numeric"
        assert events["payload"] == "jsonb"
        assert ("PRIMARY KEY", ("run_id", "sequence")) in candle_constraints
        assert ("PRIMARY KEY", ("run_id", "sequence")) in event_constraints
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_paper_trading_migration_enforces_active_account_and_immutable_records() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"paper_test_{uuid4().hex[:16]}"
    account_id = uuid4()

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        database = import_module("app.shared.database")
        database.upgrade_database(test_database_url, schema=schema)

        accounts = asyncio.run(_table_column_types(test_database_url, schema, "paper_accounts"))
        snapshots = asyncio.run(
            _table_column_types(test_database_url, schema, "paper_market_snapshots")
        )
        events = asyncio.run(
            _table_column_types(test_database_url, schema, "paper_audit_events")
        )
        event_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "paper_audit_events")
        )

        assert accounts["initial_cash"] == "numeric"
        assert accounts["last_closed_candle_at"] == "timestamp with time zone"
        assert snapshots["price"] == "numeric"
        assert events["payload"] == "jsonb"
        assert ("PRIMARY KEY", ("account_id", "sequence")) in event_constraints

        asyncio.run(_insert_paper_account(test_database_url, schema, account_id))
        with pytest.raises(DBAPIError):
            asyncio.run(_insert_paper_account(test_database_url, schema, uuid4()))

        asyncio.run(_insert_paper_intent_event(test_database_url, schema, account_id, 0))
        with pytest.raises(DBAPIError):
            asyncio.run(_insert_paper_intent_event(test_database_url, schema, account_id, 1))

        asyncio.run(_seed_paper_immutable_records(test_database_url, schema, account_id))
        asyncio.run(_assert_paper_immutable_records(test_database_url, schema))
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_agent_research_migration_adds_immutable_tables_without_rewriting_reports() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"agent_test_{uuid4().hex[:16]}"
    report_id = uuid4()

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        _upgrade_to(test_database_url, schema, "0007_paper_account_valuations")
        asyncio.run(_insert_existing_analysis_report(test_database_url, schema, report_id))
        before = asyncio.run(_analysis_report_row(test_database_url, schema, report_id))

        _upgrade_to(test_database_url, schema, "head")

        assert asyncio.run(_analysis_report_row(test_database_url, schema, report_id)) == before
        assert asyncio.run(_table_names(test_database_url, schema)) >= {
            "news_items",
            "agent_analysis_runs",
            "agent_report_details",
            "market_snapshot_inputs",
        }
        detail_columns = asyncio.run(
            _table_column_types(test_database_url, schema, "agent_report_details")
        )
        assert {
            name: detail_columns[name]
            for name in (
                "market_overview",
                "short_term_view",
                "long_term_view",
                "market_metrics",
            )
        } == {
            "market_overview": "jsonb",
            "short_term_view": "jsonb",
            "long_term_view": "jsonb",
            "market_metrics": "jsonb",
        }
        asyncio.run(_assert_agent_tables_immutable(test_database_url, schema, report_id))
        asyncio.run(_assert_market_snapshot_inputs_immutable(test_database_url, schema))
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_agent_research_migration_downgrade_fails_before_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_agent_research_migration()

    class NoSchemaMutation:
        def execute(self, _: str) -> None:
            raise AssertionError("downgrade must not mutate the schema")

    monkeypatch.setattr(migration, "op", NoSchemaMutation())

    with pytest.raises(NotImplementedError, match="不可逆"):
        migration.downgrade()


def test_market_snapshot_input_migration_downgrade_fails_before_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_market_snapshot_input_migration()

    class NoSchemaMutation:
        def execute(self, _: str) -> None:
            raise AssertionError("downgrade must not mutate the schema")

    monkeypatch.setattr(migration, "op", NoSchemaMutation())

    with pytest.raises(NotImplementedError, match="不可逆"):
        migration.downgrade()


def test_report_narrative_migration_is_forward_only_and_nullable() -> None:
    migration = _load_report_narrative_migration()
    source = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0010_expand_agent_report_narrative.py"
    ).read_text(encoding="utf-8")

    assert migration.revision == "0010_agent_report_narrative"
    assert migration.down_revision == "0009_market_snapshot_inputs"
    assert "UPDATE" not in source.upper()
    assert "DELETE" not in source.upper()
    assert "server_default" not in source


def test_report_market_metrics_migration_is_forward_only_and_nullable() -> None:
    migration = _load_report_market_metrics_migration()
    source = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0011_add_agent_report_market_metrics.py"
    ).read_text(encoding="utf-8")

    assert migration.revision == "0011_agent_report_metrics"
    assert migration.down_revision == "0010_agent_report_narrative"
    assert "UPDATE" not in source.upper()
    assert "DELETE" not in source.upper()
    assert "server_default" not in source


def test_harness_audit_migration_adds_immutable_tables_without_rewriting_reports() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"harness_test_{uuid4().hex[:16]}"
    report_id = uuid4()

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        _upgrade_to(test_database_url, schema, "0011_agent_report_metrics")
        asyncio.run(_insert_existing_analysis_report(test_database_url, schema, report_id))
        before = asyncio.run(_analysis_report_row(test_database_url, schema, report_id))

        _upgrade_to(test_database_url, schema, "head")

        assert asyncio.run(_analysis_report_row(test_database_url, schema, report_id)) == before
        assert asyncio.run(_table_names(test_database_url, schema)) >= {
            "harness_runs",
            "harness_run_events",
            "harness_evaluations",
        }
        assert asyncio.run(_table_column_types(test_database_url, schema, "harness_runs")) == {
            "run_id": "uuid",
            "run_kind": "character varying",
            "policy_version": "character varying",
            "policy_sha256": "character",
            "symbol": "character varying",
            "requested_at": "timestamp with time zone",
            "initiator_kind": "character varying",
            "request_sha256": "character",
            "created_at": "timestamp with time zone",
        }
        assert asyncio.run(
            _table_column_types(test_database_url, schema, "harness_run_events")
        ) == {
            "run_id": "uuid",
            "sequence": "integer",
            "event_kind": "character varying",
            "occurred_at": "timestamp with time zone",
            "duration_ms": "integer",
            "error_code": "character varying",
            "details": "jsonb",
        }
        assert asyncio.run(
            _table_column_types(test_database_url, schema, "harness_evaluations")
        ) == {
            "run_id": "uuid",
            "sequence": "integer",
            "evaluator_name": "character varying",
            "evaluator_version": "character varying",
            "decision": "character varying",
            "reason_code": "character varying",
            "evaluated_at": "timestamp with time zone",
            "details": "jsonb",
        }
        event_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "harness_run_events")
        )
        evaluation_constraints = asyncio.run(
            _table_constraint_columns(test_database_url, schema, "harness_evaluations")
        )
        assert ("PRIMARY KEY", ("run_id", "sequence")) in event_constraints
        assert ("PRIMARY KEY", ("run_id", "sequence")) in evaluation_constraints
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_harness_event_lifecycle_migration_enforces_exact_kind_sequence_mapping() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"harness_test_{uuid4().hex[:16]}"

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        _upgrade_to(test_database_url, schema, "head")

        for event_kind, sequence, error_code in (
            ("requested", 0, None),
            ("policy_authorized", 1, None),
            ("policy_rejected", 1, "symbol_not_allowed"),
            ("workflow_started", 2, None),
            ("workflow_completed", 3, None),
            ("workflow_degraded", 3, None),
            ("workflow_failed", 3, "workflow_exception"),
        ):
            run_id = uuid4()
            asyncio.run(_insert_harness_run_envelope(test_database_url, schema, run_id))
            asyncio.run(
                _insert_harness_event(
                    test_database_url,
                    schema,
                    run_id,
                    event_kind=event_kind,
                    sequence=sequence,
                    error_code=error_code,
                )
            )

        for event_kind, sequence, error_code in (
            ("requested", 1, None),
            ("policy_authorized", 0, None),
            ("policy_rejected", 2, "symbol_not_allowed"),
            ("workflow_started", 1, None),
            ("workflow_failed", 2, "workflow_exception"),
        ):
            run_id = uuid4()
            asyncio.run(_insert_harness_run_envelope(test_database_url, schema, run_id))
            with pytest.raises(DBAPIError):
                asyncio.run(
                    _insert_harness_event(
                        test_database_url,
                        schema,
                        run_id,
                        event_kind=event_kind,
                        sequence=sequence,
                        error_code=error_code,
                    )
                )
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_harness_audit_migration_emits_only_atomic_agent_terminal_events() -> None:
    test_database_url = AppSettings().test_database_url
    assert test_database_url is not None
    schema = f"harness_test_{uuid4().hex[:16]}"
    completed_run_id = uuid4()
    degraded_run_id = uuid4()
    direct_run_id = uuid4()

    asyncio.run(_create_schema(test_database_url, schema))
    try:
        _upgrade_to(test_database_url, schema, "head")

        asyncio.run(_seed_harness_run(test_database_url, schema, completed_run_id))
        asyncio.run(
            _insert_agent_analysis_run(
                test_database_url,
                schema,
                completed_run_id,
                status="completed",
                completed_at=HARNESS_TEST_NOW + timedelta(milliseconds=1234, microseconds=999),
            )
        )
        assert asyncio.run(_terminal_events(test_database_url, schema, completed_run_id)) == [
            (0, "requested", None),
            (1, "policy_authorized", None),
            (2, "workflow_started", None),
            (3, "workflow_completed", None),
        ]
        assert asyncio.run(
            _terminal_event_payload(test_database_url, schema, completed_run_id)
        ) == (
            HARNESS_TEST_NOW + timedelta(milliseconds=1234, microseconds=999),
            1234,
            {},
        )

        asyncio.run(
            _seed_harness_run(
                test_database_url,
                schema,
                degraded_run_id,
                requested_at=HARNESS_TEST_NOW + timedelta(seconds=3),
            )
        )
        asyncio.run(
            _insert_agent_analysis_run(
                test_database_url,
                schema,
                degraded_run_id,
                status="degraded",
                error_code="partial_data",
                completed_at=HARNESS_TEST_NOW + timedelta(seconds=2),
            )
        )
        assert asyncio.run(_terminal_events(test_database_url, schema, degraded_run_id)) == [
            (0, "requested", None),
            (1, "policy_authorized", None),
            (2, "workflow_started", None),
            (3, "workflow_degraded", "partial_data"),
        ]
        assert asyncio.run(_terminal_event_payload(test_database_url, schema, degraded_run_id)) == (
            HARNESS_TEST_NOW + timedelta(seconds=2),
            0,
            {},
        )

        asyncio.run(
            _insert_direct_agent_run_with_qualified_tables(
                test_database_url,
                schema,
                direct_run_id,
                completed_at=HARNESS_TEST_NOW,
            )
        )
        assert asyncio.run(_terminal_events(test_database_url, schema, direct_run_id)) == []

        asyncio.run(_assert_harness_tables_immutable(test_database_url, schema))
    finally:
        asyncio.run(_drop_schema(test_database_url, schema))


def test_harness_audit_migration_downgrade_fails_before_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_harness_audit_migration()

    class NoSchemaMutation:
        def __getattr__(self, _: str) -> object:
            raise AssertionError("downgrade must not mutate the schema")

    monkeypatch.setattr(migration, "op", NoSchemaMutation())

    with pytest.raises(
        NotImplementedError,
        match="Harness 审计迁移不可逆，禁止删除审计记录",
    ):
        migration.downgrade()


def test_all_migration_revisions_fit_the_default_alembic_version_column() -> None:
    migrations_directory = Path(__file__).resolve().parents[2] / "alembic" / "versions"

    for migration_path in migrations_directory.glob("*.py"):
        migration = _load_migration(migration_path.name, migration_path.stem)
        assert len(migration.revision) <= 32


def _load_agent_research_migration() -> ModuleType:
    return _load_migration("0008_create_agent_research.py", "agent_research_migration")


def _load_market_snapshot_input_migration() -> ModuleType:
    return _load_migration(
        "0009_create_immutable_market_snapshot_inputs.py",
        "market_snapshot_input_migration",
    )


def _load_report_narrative_migration() -> ModuleType:
    return _load_migration(
        "0010_expand_agent_report_narrative.py",
        "report_narrative_migration",
    )


def _load_report_market_metrics_migration() -> ModuleType:
    return _load_migration(
        "0011_add_agent_report_market_metrics.py",
        "report_market_metrics_migration",
    )


def _load_harness_audit_migration() -> ModuleType:
    return _load_migration(
        "0012_create_harness_audit.py",
        "harness_audit_migration",
    )


def _load_migration(filename: str, module_name: str) -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / filename
    )
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load agent research migration")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _upgrade_to(database_url: SecretStr, schema: str, revision: str) -> None:
    configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    configuration.set_main_option("sqlalchemy.url", database_url.get_secret_value())
    configuration.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.upgrade(configuration, revision)


async def _insert_existing_analysis_report(
    database_url: SecretStr,
    schema: str,
    report_id: object,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO analysis_reports ("
            "id, analysis_id, symbol, status, title, summary, facts, inferences, risks, "
            "limitations, generated_at, data_cutoff_at"
            ") VALUES ("
            ":id, :id, 'BTCUSDT', 'degraded', 'existing', 'existing', "
            "'[]'::jsonb, '[]'::jsonb, '[\"risk\"]'::jsonb, '[\"limit\"]'::jsonb, "
            ":generated_at, NULL"
            ")"
        ),
        {"id": report_id, "generated_at": AGENT_TEST_NOW},
    )


async def _analysis_report_row(
    database_url: SecretStr,
    schema: str,
    report_id: object,
) -> tuple[object, ...]:
    engine = _database_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            result = await connection.execute(
                text(
                    "SELECT id, analysis_id, symbol, status, title, summary, facts, "
                    "inferences, risks, limitations, generated_at, data_cutoff_at, created_at "
                    "FROM analysis_reports WHERE id = :id"
                ),
                {"id": report_id},
            )
            return tuple(result.one())
    finally:
        await engine.dispose()


async def _seed_harness_run(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
    *,
    requested_at: datetime = HARNESS_TEST_NOW,
) -> None:
    await _insert_existing_analysis_report(database_url, schema, run_id)
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(
                text(
                    "INSERT INTO harness_runs ("
                    "run_id, run_kind, policy_version, policy_sha256, symbol, requested_at, "
                    "initiator_kind, request_sha256"
                    ") VALUES ("
                    ":run_id, 'market_research', 'market_research_v1', :policy_sha256, "
                    "'BTCUSDT', :requested_at, 'manual_api', :request_sha256"
                    ")"
                ),
                {
                    "run_id": run_id,
                    "policy_sha256": "a" * 64,
                    "requested_at": requested_at,
                    "request_sha256": "b" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO harness_run_events ("
                    "run_id, sequence, event_kind, occurred_at, duration_ms, error_code, details"
                    ") VALUES "
                    "(:run_id, 0, 'requested', :occurred_at, 0, NULL, "
                    '\'{"workflow_kind": "market_research"}\'::jsonb), '
                    "(:run_id, 1, 'policy_authorized', :occurred_at, 0, NULL, "
                    "'{\"allowed_capability_count\": 1}'::jsonb), "
                    "(:run_id, 2, 'workflow_started', :occurred_at, 0, NULL, "
                    '\'{"workflow_kind": "market_research"}\'::jsonb)'
                ),
                {"run_id": run_id, "occurred_at": requested_at},
            )
            await connection.execute(
                text(
                    "INSERT INTO harness_evaluations ("
                    "run_id, sequence, evaluator_name, evaluator_version, decision, "
                    "reason_code, evaluated_at, details"
                    ") VALUES ("
                    ":run_id, 0, 'policy_allowlist', '1', 'passed', NULL, "
                    ":evaluated_at, '{\"allowed_capability_count\": 1}'::jsonb"
                    ")"
                ),
                {"run_id": run_id, "evaluated_at": requested_at},
            )
    finally:
        await engine.dispose()


async def _insert_agent_analysis_run(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
    *,
    status: str,
    completed_at: datetime,
    error_code: str | None = None,
) -> None:
    if not await _analysis_report_exists(database_url, schema, run_id):
        await _insert_existing_analysis_report(database_url, schema, run_id)
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO agent_analysis_runs ("
            "id, analysis_id, symbol, status, started_at, completed_at, generator_kind, "
            "error_code"
            ") VALUES ("
            ":id, :analysis_id, 'BTCUSDT', :status, :started_at, :completed_at, "
            "'langgraph_deepseek', :error_code"
            ")"
        ),
        {
            "id": uuid4(),
            "analysis_id": run_id,
            "status": status,
            "started_at": HARNESS_TEST_NOW,
            "completed_at": completed_at,
            "error_code": error_code,
        },
    )


async def _analysis_report_exists(
    database_url: SecretStr,
    schema: str,
    report_id: UUID,
) -> bool:
    rows = await _rows_in_schema(
        database_url,
        schema,
        text("SELECT 1 FROM analysis_reports WHERE id = :id"),
        {"id": report_id},
    )
    return bool(rows)


async def _insert_direct_agent_run_with_qualified_tables(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
    *,
    completed_at: datetime,
) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".analysis_reports ('
                    "id, analysis_id, symbol, status, title, summary, facts, inferences, "
                    "risks, limitations, generated_at, data_cutoff_at"
                    ") VALUES ("
                    ":id, :id, 'BTCUSDT', 'completed', 'direct', 'direct', "
                    "'[]'::jsonb, '[]'::jsonb, '[\"risk\"]'::jsonb, "
                    "'[\"limit\"]'::jsonb, :generated_at, NULL"
                    ")"
                ),
                {"id": run_id, "generated_at": completed_at},
            )
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".agent_analysis_runs ('
                    "id, analysis_id, symbol, status, started_at, completed_at, "
                    "generator_kind, error_code"
                    ") VALUES ("
                    ":id, :analysis_id, 'BTCUSDT', 'completed', :started_at, "
                    ":completed_at, 'langgraph_deepseek', NULL"
                    ")"
                ),
                {
                    "id": uuid4(),
                    "analysis_id": run_id,
                    "started_at": completed_at,
                    "completed_at": completed_at,
                },
            )
    finally:
        await engine.dispose()


async def _insert_harness_run_envelope(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO harness_runs ("
            "run_id, run_kind, policy_version, policy_sha256, symbol, requested_at, "
            "initiator_kind, request_sha256"
            ") VALUES ("
            ":run_id, 'market_research', 'market_research_v1', :policy_sha256, "
            "'BTCUSDT', :requested_at, 'manual_api', :request_sha256"
            ")"
        ),
        {
            "run_id": run_id,
            "policy_sha256": "a" * 64,
            "requested_at": HARNESS_TEST_NOW,
            "request_sha256": "b" * 64,
        },
    )


async def _insert_harness_event(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
    *,
    event_kind: str,
    sequence: int,
    error_code: str | None,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO harness_run_events ("
            "run_id, sequence, event_kind, occurred_at, duration_ms, error_code, details"
            ") VALUES ("
            ":run_id, :sequence, :event_kind, :occurred_at, 0, :error_code, '{}'::jsonb"
            ")"
        ),
        {
            "run_id": run_id,
            "sequence": sequence,
            "event_kind": event_kind,
            "occurred_at": HARNESS_TEST_NOW,
            "error_code": error_code,
        },
    )


async def _terminal_events(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
) -> list[tuple[int, str, str | None]]:
    rows = await _rows_in_schema(
        database_url,
        schema,
        text(
            "SELECT sequence, event_kind, error_code FROM harness_run_events "
            "WHERE run_id = :run_id ORDER BY sequence"
        ),
        {"run_id": run_id},
    )
    terminal_events: list[tuple[int, str, str | None]] = []
    for sequence, event_kind, error_code in rows:
        assert isinstance(sequence, int)
        assert isinstance(event_kind, str)
        assert error_code is None or isinstance(error_code, str)
        terminal_events.append((sequence, event_kind, error_code))
    return terminal_events


async def _terminal_event_payload(
    database_url: SecretStr,
    schema: str,
    run_id: UUID,
) -> tuple[datetime, int, object]:
    rows = await _rows_in_schema(
        database_url,
        schema,
        text(
            "SELECT occurred_at, duration_ms, details FROM harness_run_events "
            "WHERE run_id = :run_id AND sequence = 3"
        ),
        {"run_id": run_id},
    )
    occurred_at, duration_ms, details = rows[0]
    assert isinstance(occurred_at, datetime)
    assert isinstance(duration_ms, int)
    return occurred_at, duration_ms, details


async def _assert_harness_tables_immutable(
    database_url: SecretStr,
    schema: str,
) -> None:
    assignments = {
        "harness_runs": "symbol = symbol",
        "harness_run_events": "duration_ms = duration_ms",
        "harness_evaluations": "decision = decision",
    }
    for table, assignment in assignments.items():
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(
                database_url,
                schema,
                text(f"UPDATE {table} SET {assignment}"),
                {},
            )
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(
                database_url,
                schema,
                text(f"DELETE FROM {table}"),
                {},
            )


async def _rows_in_schema(
    database_url: SecretStr,
    schema: str,
    statement: object,
    parameters: dict[str, object],
) -> list[tuple[object, ...]]:
    engine = _database_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            result = await connection.execute(statement, parameters)
            return [tuple(row) for row in result.all()]
    finally:
        await engine.dispose()


async def _table_names(database_url: SecretStr, schema: str) -> set[str]:
    engine = _database_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema"
                ),
                {"schema": schema},
            )
            return set(result.scalars())
    finally:
        await engine.dispose()


async def _assert_agent_tables_immutable(
    database_url: SecretStr,
    schema: str,
    report_id: object,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO agent_analysis_runs ("
            "id, analysis_id, symbol, status, started_at, completed_at, generator_kind"
            ") VALUES ("
            ":id, :report_id, 'BTCUSDT', 'degraded', :started_at, :completed_at, "
            "'langgraph_deepseek'"
            ")"
        ),
        {
            "id": uuid4(),
            "report_id": report_id,
            "started_at": AGENT_TEST_NOW,
            "completed_at": AGENT_TEST_NOW,
        },
    )
    statements = {
        "news_items": "DELETE FROM news_items",
        "agent_analysis_runs": "UPDATE agent_analysis_runs SET status = status",
        "agent_report_details": "DELETE FROM agent_report_details",
    }
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO news_items ("
            "id, deduplication_key, source_id, source_tier, published_at, fetched_at, "
            "language, title, summary, related_symbols, event_category, content_hash"
            ") VALUES ("
            ":id, 'migration:item', 'coindesk', 'professional_media', :published_at, "
            ":fetched_at, 'en', 'title', 'summary', '[\"BTCUSDT\"]'::jsonb, "
            "'market', :content_hash"
            ")"
        ),
        {
            "id": uuid4(),
            "published_at": AGENT_TEST_NOW,
            "fetched_at": AGENT_TEST_NOW,
            "content_hash": "a" * 64,
        },
    )
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO agent_report_details ("
            "analysis_report_id, horizon, outlook, confidence, trend_alignment, "
            "support_zones, resistance_zones, catalysts, risks_and_invalidation, "
            "data_quality, limitations"
            ") VALUES ("
            ":report_id, '1_to_3_days', 'neutral', 'low', '{}'::jsonb, '[]'::jsonb, "
            "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb"
            ")"
        ),
        {"report_id": report_id},
    )
    for statement in statements.values():
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(database_url, schema, text(statement), {})


async def _assert_market_snapshot_inputs_immutable(
    database_url: SecretStr,
    schema: str,
) -> None:
    snapshot_id = uuid4()
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO market_snapshots ("
            "id, symbol, source, captured_at, data_as_of, data_version, payload, payload_sha256"
            ") VALUES ("
            ":id, 'BTCUSDT', 'binance_usdm_public_rest', :captured_at, :data_as_of, "
            "'market-v1', '{\"summary\": {}}'::jsonb, :payload_sha256"
            ")"
        ),
        {
            "id": snapshot_id,
            "captured_at": AGENT_TEST_NOW,
            "data_as_of": AGENT_TEST_NOW,
            "payload_sha256": "a" * 64,
        },
    )
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO market_snapshot_inputs ("
            "snapshot_id, symbol, payload, payload_sha256, candle_count"
            ") VALUES ("
            ":snapshot_id, 'BTCUSDT', '{\"candles\": [{}]}'::jsonb, :payload_sha256, 1"
            ")"
        ),
        {"snapshot_id": snapshot_id, "payload_sha256": "b" * 64},
    )
    for statement in (
        "UPDATE market_snapshot_inputs SET candle_count = candle_count",
        "DELETE FROM market_snapshot_inputs",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(database_url, schema, text(statement), {})


async def _create_schema(database_url: SecretStr, schema: str) -> None:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


async def _version_table_schemas(database_url: SecretStr) -> list[str]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version' ORDER BY table_schema",
                ),
            )
            return list(result.scalars())
    finally:
        await engine.dispose()


async def _table_column_types(
    database_url: SecretStr,
    schema: str,
    table: str,
) -> dict[str, str]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table",
                ),
                {"schema": schema, "table": table},
            )
            return dict(result.all())
    finally:
        await engine.dispose()


async def _table_constraint_columns(
    database_url: SecretStr,
    schema: str,
    table: str,
) -> set[tuple[str, tuple[str, ...]]]:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT constraint_type, constraint_name "
                    "FROM information_schema.table_constraints "
                    "WHERE table_schema = :schema AND table_name = :table",
                ),
                {"schema": schema, "table": table},
            )
            constraints: set[tuple[str, tuple[str, ...]]] = set()
            for constraint_type, constraint_name in result.tuples():
                column_result = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.key_column_usage "
                        "WHERE table_schema = :schema AND table_name = :table "
                        "AND constraint_name = :constraint_name ORDER BY ordinal_position",
                    ),
                    {
                        "schema": schema,
                        "table": table,
                        "constraint_name": constraint_name,
                    },
                )
                constraints.add((constraint_type, tuple(column_result.scalars())))
            return constraints
    finally:
        await engine.dispose()


async def _drop_schema(database_url: SecretStr, schema: str) -> None:
    database = import_module("app.shared.database")
    engine = database.create_async_engine_from_secret(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()


async def _insert_paper_account(
    database_url: SecretStr,
    schema: str,
    account_id: object,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO paper_accounts ("
            "id, status, symbol, initial_cash, cash, equity, peak_equity, "
            "daily_start_equity, daily_realized_loss, daily_day, cooldown_remaining, "
            "risk_config, execution_config, created_at"
            ") VALUES ("
            ":id, 'active', 'BTCUSDT', 10000, 10000, 10000, 10000, "
            "10000, 0, DATE '2026-08-04', 0, '{}'::jsonb, '{}'::jsonb, :created_at"
            ")"
        ),
        {"id": account_id, "created_at": PAPER_TEST_NOW},
    )


async def _insert_paper_intent_event(
    database_url: SecretStr,
    schema: str,
    account_id: object,
    sequence: int,
) -> None:
    await _execute_in_schema(
        database_url,
        schema,
        text(
            "INSERT INTO paper_audit_events ("
            "account_id, sequence, kind, occurred_at, idempotency_key, payload"
            ") VALUES ("
            ":account_id, :sequence, 'intent', :occurred_at, 'manual:duplicate', '{}'::jsonb"
            ")"
        ),
        {
            "account_id": account_id,
            "sequence": sequence,
            "occurred_at": PAPER_TEST_NOW,
        },
    )


async def _seed_paper_immutable_records(
    database_url: SecretStr,
    schema: str,
    account_id: object,
) -> None:
    snapshot_id = uuid4()
    order_id = uuid4()
    fill_id = uuid4()
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(
                text(
                    "INSERT INTO paper_market_snapshots ("
                    "id, account_id, price, source, observed_at, fetched_at, payload_hash"
                    ") VALUES ("
                    ":id, :account_id, 100, 'binance_usdm_public', :observed_at, "
                    ":fetched_at, :payload_hash"
                    ")"
                ),
                {
                    "id": snapshot_id,
                    "account_id": account_id,
                    "observed_at": PAPER_TEST_NOW,
                    "fetched_at": PAPER_TEST_NOW,
                    "payload_hash": "a" * 64,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_orders ("
                    "id, account_id, snapshot_id, action, source, idempotency_key, "
                    "submitted_at, requested_quantity, status"
                    ") VALUES ("
                    ":id, :account_id, :snapshot_id, 'open_long', 'manual', "
                    "'manual:immutable', :submitted_at, 1, 'filled'"
                    ")"
                ),
                {
                    "id": order_id,
                    "account_id": account_id,
                    "snapshot_id": snapshot_id,
                    "submitted_at": PAPER_TEST_NOW,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_fills ("
                    "id, order_id, account_id, quantity, price, fee, filled_at, status"
                    ") VALUES ("
                    ":id, :order_id, :account_id, 1, 100, 0.1, :filled_at, 'filled'"
                    ")"
                ),
                {
                    "id": fill_id,
                    "order_id": order_id,
                    "account_id": account_id,
                    "filled_at": PAPER_TEST_NOW,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_ledger_entries ("
                    "account_id, sequence, occurred_at, kind, cash_delta, position_delta, "
                    "realized_pnl, fee, cash_after, quantity_after"
                    ") VALUES ("
                    ":account_id, 0, :occurred_at, 'open_long', -100.1, 1, 0, 0.1, "
                    "9899.9, 1"
                    ")"
                ),
                {"account_id": account_id, "occurred_at": PAPER_TEST_NOW},
            )
            await connection.execute(
                text(
                    "INSERT INTO paper_audit_events ("
                    "account_id, sequence, kind, occurred_at, idempotency_key, payload"
                    ") VALUES ("
                    ":account_id, 2, 'fill', :occurred_at, 'manual:immutable', '{}'::jsonb"
                    ")"
                ),
                {"account_id": account_id, "occurred_at": PAPER_TEST_NOW},
            )
    finally:
        await engine.dispose()


async def _assert_paper_immutable_records(database_url: SecretStr, schema: str) -> None:
    assignments = {
        "paper_market_snapshots": "price = price",
        "paper_orders": "status = status",
        "paper_fills": "fee = fee",
        "paper_ledger_entries": "cash_after = cash_after",
        "paper_audit_events": "payload = payload",
    }
    for table, assignment in assignments.items():
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(
                database_url,
                schema,
                text(f"UPDATE {table} SET {assignment}"),
                {},
            )
        with pytest.raises(DBAPIError, match="immutable"):
            await _execute_in_schema(
                database_url,
                schema,
                text(f"DELETE FROM {table}"),
                {},
            )


def _database_engine(database_url: SecretStr):
    database = import_module("app.shared.database")
    return database.create_async_engine_from_secret(database_url)


async def _execute_in_schema(
    database_url: SecretStr,
    schema: str,
    statement: object,
    parameters: dict[str, object],
) -> None:
    engine = _database_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.execute(statement, parameters)
    finally:
        await engine.dispose()
