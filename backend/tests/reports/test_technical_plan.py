from uuid import uuid4

import pytest

from app.reports.technical import TechnicalReport
from app.reports.technical_plan import parse_technical_report
from tests.agent.test_technical_engine import NOW
from tests.agent.test_technical_references import context


def test_v1_round_trip_unchanged() -> None:
    report = TechnicalReport(
        id=uuid4(),
        analysis_id=uuid4(),
        symbol="BTCUSDT",
        status="degraded",
        created_at=NOW,
        data_cutoff_at=NOW,
        analysis=context().analysis,
        narrative=None,
        error_code="model_not_configured",
    )
    assert parse_technical_report(report.model_dump(mode="json")).model_dump(
        mode="json"
    ) == report.model_dump(mode="json")


def test_unknown_report_version_rejected() -> None:
    report = TechnicalReport(
        id=uuid4(),
        analysis_id=uuid4(),
        symbol="BTCUSDT",
        status="degraded",
        created_at=NOW,
        data_cutoff_at=NOW,
        analysis=context().analysis,
        narrative=None,
        error_code="model_not_configured",
    )
    with pytest.raises(ValueError):
        parse_technical_report({**report.model_dump(mode="json"), "version": "technical-v9"})
