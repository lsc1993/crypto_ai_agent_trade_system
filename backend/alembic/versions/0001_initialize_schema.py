"""Initialize the Alembic revision chain."""

from collections.abc import Sequence

revision: str = "0001_initialize_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
