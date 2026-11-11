# T05 正式审查修复的账本 schema 加固：允许发送前失败不伪造 sent_at，定义 released 释放态，
# 并用 INSERT/UPDATE 共用的 CHECK 约束限制 meter/state 下 actual_amount 的合法形状。
# 本迁移只前向修改 0023 建立的约束/触发器，不改写历史迁移、不删除账本行。
# 0024 尚未应用到业务库；回退会删除审计约束，因此明确拒绝。
"""Harden agent attempt timestamps and budget reservation shapes."""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_agent_attempt_hardening"
down_revision: str | None = "0023_agent_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 只替换约束与触发器函数；既有表、索引、行和 revision 0019–0023 保持不变。
def upgrade() -> None:
    # 发送前 failed 没有 sent_at；发送后 failed 仍由应用保留 sent_at，二者都允许。
    op.drop_constraint("ck_agent_attempt_timestamps", "agent_attempts", type_="check")
    op.create_check_constraint(
        "ck_agent_attempt_timestamps",
        "agent_attempts",
        "(status = 'prepared' AND sent_at IS NULL AND settled_at IS NULL) OR "
        "(status = 'in_flight' AND sent_at IS NOT NULL AND settled_at IS NULL) OR "
        "(status = 'failed' AND settled_at IS NOT NULL) OR "
        "(status IN ('succeeded','unknown') AND sent_at IS NOT NULL "
        "AND settled_at IS NOT NULL)",
    )

    # released 仅用于未发送的 prepared 终止，释放次数/Token 预留但保留审计行。
    op.drop_constraint("ck_budget_reservation_state", "budget_reservations", type_="check")
    op.create_check_constraint(
        "ck_budget_reservation_state",
        "budget_reservations",
        "state IN ('reserved','charged','settled','unknown','released')",
    )

    # 关键形状规则：CHECK 同时作用于 INSERT 和 UPDATE，防止 reserved Token 提前写 actual=0。
    # 次数 meter 在 charged 时允许 actual=1；未结算 Token 的 actual 必须为 NULL。
    op.create_check_constraint(
        "ck_budget_reservation_shape",
        "budget_reservations",
        "(meter = 'activity_seconds' AND attempt_id IS NULL AND state = 'settled' "
        "AND reserved_amount = 0 AND actual_amount IS NOT NULL) OR "
        "(meter IN ('model_calls','tool_calls','transport_calls') AND attempt_id IS NOT NULL "
        "AND ((state IN ('reserved','unknown','released') AND actual_amount IS NULL) "
        "OR (state = 'charged' AND (actual_amount IS NULL OR actual_amount = 1)) "
        "OR (state = 'settled' AND actual_amount = 1))) OR "
        "(meter IN ('input_tokens','output_tokens') AND attempt_id IS NOT NULL "
        "AND ((state IN ('reserved','charged','unknown','released') "
        "AND actual_amount IS NULL) "
        "OR (state = 'settled' AND actual_amount IS NOT NULL)))",
    )

    # 允许 reserved→released（发送前失败释放），但已发送的 charged 不能释放或回写。
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_budget_reservation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.run_id IS DISTINCT FROM OLD.run_id
               OR NEW.segment_id IS DISTINCT FROM OLD.segment_id
               OR NEW.meter IS DISTINCT FROM OLD.meter
               OR NEW.reserved_amount IS DISTINCT FROM OLD.reserved_amount
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'budget reservation identity is immutable';
            END IF;
            IF OLD.state IN ('settled','released') THEN
                RAISE EXCEPTION 'budget reservation is terminal';
            ELSIF OLD.state = 'unknown'
                  AND NEW.state NOT IN ('unknown','settled') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            ELSIF OLD.state = 'reserved'
                  AND NEW.state NOT IN ('reserved','charged','settled','unknown','released') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            ELSIF OLD.state = 'charged'
                  AND NEW.state NOT IN ('charged','settled','unknown') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            END IF;
            IF NEW.state = 'settled' AND NEW.actual_amount IS NULL THEN
                RAISE EXCEPTION 'settled budget reservation requires actual amount';
            END IF;
            IF NEW.state = 'unknown' AND NEW.actual_amount IS NOT NULL THEN
                RAISE EXCEPTION 'unknown budget reservation cannot carry actual amount';
            END IF;
            IF NEW.state = 'released' AND NEW.actual_amount IS NOT NULL THEN
                RAISE EXCEPTION 'released budget reservation cannot carry actual amount';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


# 前向迁移拒绝回退，避免删除审计约束与账本历史。
def downgrade() -> None:
    raise NotImplementedError("Agent 尝试与预算加固迁移不可逆，禁止删除审计历史")
