# 将 Harness 事件类型与生命周期序号绑定为数据库检查。
# 请求固定在首位、开始在次位、结束在末位，避免合法类型出现在错误位置。
"""Enforce immutable Harness audit event lifecycle positions."""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_harness_event_lifecycle"
down_revision: str | None = "0012_harness_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
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


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("Harness 审计生命周期迁移不可逆，禁止删除审计记录")
