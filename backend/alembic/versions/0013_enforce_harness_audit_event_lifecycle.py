"""Enforce immutable Harness audit event lifecycle positions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_harness_event_lifecycle"
down_revision: str | None = "0012_harness_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_harness_run_events_lifecycle",
        "harness_run_events",
        "(event_kind = 'requested' AND sequence = 0) OR "
        "(event_kind IN ('policy_authorized', 'policy_rejected') AND sequence = 1) OR "
        "(event_kind = 'workflow_started' AND sequence = 2) OR "
        "(event_kind IN ('workflow_completed', 'workflow_degraded', 'workflow_failed') "
        "AND sequence = 3)",
    )


def downgrade() -> None:
    raise NotImplementedError("Harness 审计生命周期迁移不可逆，禁止删除审计记录")
