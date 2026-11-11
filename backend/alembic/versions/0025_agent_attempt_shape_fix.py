# T05 复审剩余问题 R1 的前向修复：收紧次数 meter 的 settled 形状。
# 0024 的 settled 分支只有 actual_amount = 1；actual 为 NULL 时 SQL 三值逻辑使整个 CHECK 得到 NULL，
# PostgreSQL 会放行。本迁移替换同一约束，显式要求非空且等于 1，覆盖 INSERT 与 UPDATE。
# 不改写 0024 或更早迁移；0024 已建立的表、索引、触发器和历史行保持不变。
"""Require non-null actual amount for settled call-count reservations."""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_agent_attempt_shape_fix"
down_revision: str | None = "0024_agent_attempt_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 仅替换形状约束；合法历史行（settled 次数 actual=1）不受影响。
def upgrade() -> None:
    op.drop_constraint("ck_budget_reservation_shape", "budget_reservations", type_="check")
    op.create_check_constraint(
        "ck_budget_reservation_shape",
        "budget_reservations",
        "(meter = 'activity_seconds' AND attempt_id IS NULL AND state = 'settled' "
        "AND reserved_amount = 0 AND actual_amount IS NOT NULL) OR "
        "(meter IN ('model_calls','tool_calls','transport_calls') AND attempt_id IS NOT NULL "
        "AND ((state IN ('reserved','unknown','released') AND actual_amount IS NULL) "
        "OR (state = 'charged' AND (actual_amount IS NULL OR actual_amount = 1)) "
        "OR (state = 'settled' AND actual_amount IS NOT NULL AND actual_amount = 1))) OR "
        "(meter IN ('input_tokens','output_tokens') AND attempt_id IS NOT NULL "
        "AND ((state IN ('reserved','charged','unknown','released') "
        "AND actual_amount IS NULL) "
        "OR (state = 'settled' AND actual_amount IS NOT NULL)))",
    )


# 前向迁移拒绝回退；回退会重新引入 NULL 三值逻辑放行缺口。
def downgrade() -> None:
    raise NotImplementedError("Agent 尝试预算形状修复不可逆，禁止重新放行非法账本")
