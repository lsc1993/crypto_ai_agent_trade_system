# 初始化迁移修订链，仅建立 Alembic 的起点。
# upgrade 与 downgrade 都为空操作，不创建业务表。
"""Initialize the Alembic revision chain."""

from collections.abc import Sequence

revision: str = "0001_initialize_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 起始修订没有业务变更，仅使后续迁移拥有稳定父节点。
def upgrade() -> None:
    pass


# 空起始修订没有需要撤销的业务对象。
def downgrade() -> None:
    pass
