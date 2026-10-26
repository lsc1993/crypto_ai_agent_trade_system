# Alembic 生成迁移的模板；生成后需补充本次变化的目的、兼容性和实际回退限制。
"""${message}"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# 修订号与父修订维护历史链，不得为注释整理改写已应用的修订关系。
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


# 前向变化由自动生成片段填入；提交前需检查约束、索引和历史数据兼容性。
def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


# 模板提供回退占位，具体迁移是否允许回退必须依据审计保留要求明确决定。
def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
